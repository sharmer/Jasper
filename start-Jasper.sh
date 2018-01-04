#!/bin/bash

# Copyright 2017 Mycroft AI Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

SOURCE="${BASH_SOURCE[0]}"

script=${0}
script=${script##*/}
DIR="$( cd -P "$( dirname "$SOURCE" )" && pwd )"

if [ -z "$WORKON_HOME" ]; then
    VIRTUALENV_ROOT=${VIRTUALENV_ROOT:-"${HOME}/.virtualenvs/Jasper"}
else
    VIRTUALENV_ROOT="$WORKON_HOME/Jasper"
fi

function help() {
  echo "${script}:  Jasper launcher"
  echo "usage: ${script} "
  #echo "usage: ${script} [command] [params]"
  #echo
  #echo "Services:"
  #echo "  all                      runs Jasper"
  #echo "  debug                    runs Jasper in debug mode"
  #echo

  exit 1
}

_script="{DIR}/mycroft/messagebus/service/main.py"
first_time=true

function launch-Jasper() {
    if ($first_time) ; then
        echo "Initializing..."
        source ${VIRTUALENV_ROOT}/bin/activate
        first_time=false
    fi

    # Launch process in background, sending log to scripts/log/mycroft-*.log
    echo "Starting $1"
    python ${_script} $_params
}

_opt=$1
shift
_params=$@

launch-Jasper
