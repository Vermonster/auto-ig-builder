import logging
import os
import random
import requests
import shutil
import string
import subprocess
import sys

from .util  import make_temp_dir, do, send_zulip
from os.path import normpath

GITHUB = 'https://github.com/%(org)s/%(repo)s'
HOSTED_ROOT = os.environ.get('HOSTED_ROOT', 'http://build.fhir.org/ig')
PUBLISHER_JAR_URL = os.environ.get('PUBLISHER_JAR_URL', 'https://github.com/HL7/fhir-ig-publisher/releases/latest/download/publisher.jar')
TX_SERVER_URL = os.environ.get('TX_SERVER_URL', 'http://tx.fhir.org/r4')

def get_qa_score(build_dir):
  qa_file = os.path.join(build_dir, 'qa.html')
  try:
    with open(qa_file, 'r') as f:
      f.readline()
      f.readline()
      report_line = f.readline()
    return report_line.split("--")[1].strip()
  except:
    return "No QA File"


def build(config):

  if config['branch'] == 'gh-pages':
    sys.exit(0)

  temp_dir = make_temp_dir()
  clone_dir = os.path.join(temp_dir, 'repo')
  build_dir = os.path.join(clone_dir, 'output')
  logfile = os.path.join(temp_dir, 'build.log')
  logging.basicConfig(filename=logfile, level=logging.DEBUG)
  logging.info('about to clone!')

  def run_git_cmd(cmds):
    return subprocess.check_output(cmds, cwd=clone_dir, universal_newlines=True).strip()

  def is_default_branch():
    default_branch_full = run_git_cmd(['git', 'symbolic-ref', 'refs/remotes/origin/HEAD'])
    default_branch = default_branch_full.split('/')[-1]
    return bool(default_branch == config['branch'])

  do(['git', 'clone', '--recursive', GITHUB%config, '--branch', config['branch'], 'repo'], temp_dir, deadline=True)
  do(['wget', '-q', PUBLISHER_JAR_URL, '-O', 'publisher.jar'], temp_dir, deadline=True)
  do(['npm', '-g', 'install', 'fsh-sushi'], temp_dir, deadline=True)

  details = {
    'root': HOSTED_ROOT,
    'org': config['org'],
    'repo': config['repo'],
    'branch': config['branch'],
    'default': 'default' if is_default_branch() else 'nondefault',
    'commit': run_git_cmd(['git', 'log', '-1', '--pretty=%B (%an)'])
  }

  java_memory = os.environ.get('JAVA_MEMORY', '2g')

  built_exit = do(['java',
         '-Xms%s'%java_memory, '-Xmx%s'%java_memory,
         '-jar', '../publisher.jar',
         '-ig', 'ig.json',
         '-api-key-file', '/etc/ig.builder.keyfile.ini',
         '-auto-ig-build',
         '-tx', TX_SERVER_URL,
         '-target', 'https://build.fhir.org/ig/%s/%s/'%(details['org'], details['repo']),
         '-out', clone_dir], clone_dir, deadline=True)
  built = (0 == built_exit)
  print(built, built_exit)

  message = ["**[%(org)s/%(repo)s: %(branch)s](https://github.com/%(org)s/%(repo)s/tree/%(branch)s)** rebuilt\n",
             "Commit: %(commit)s :%(emoji)s:\n",
             "Details: [build logs](%(root)s/%(org)s/%(repo)s/branches/%(branch)s/%(buildlog)s)"]

  if not built:
    print("Build error occurred")
    details['emoji'] = 'thumbs_down'
    details['buildlog'] = 'failure/build.log'
    message += [" | [debug](%(root)s/%(org)s/%(repo)s/branches/%(branch)s/failure)"]
    shutil.copy(logfile, clone_dir)
    do(['publish', details['org'], details['repo'], details['branch'], 'failure', details['default']], clone_dir, pipe=True)
  else:
    print("Build succeeded")
    details['emoji'] = 'thumbs_up'
    details['buildlog'] = 'build.log'
    message += [" | [published](%(root)s/%(org)s/%(repo)s/branches/%(branch)s/index.html)"]
    message += [" | [qa: %s]"%get_qa_score(build_dir), "(%(root)s/%(org)s/%(repo)s/branches/%(branch)s/qa.html)"]
    print("Copying logfile")
    shutil.copy(logfile, build_dir)
    print("publishing")
    do(['publish', details['org'], details['repo'], details['branch'], 'success', details['default']], build_dir, pipe=True)
    print("published")

  send_zulip('committers/notification', 'ig-build', "".join(message)%details)
  # sys.exit(0 if built else 1)

if __name__ == '__main__':
  build({
    'org': os.environ.get('IG_ORG', 'test-igs'),
    'repo': os.environ.get('IG_REPO', 'simple'),
    'branch': os.environ.get('IG_BRANCH', 'master'),
  })
