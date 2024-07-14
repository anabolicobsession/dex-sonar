#!/bin/bash

heroku config:set $(tr '\n' ' ' <<< "$(cat .env)")
git push -f heroku "$1":main

heroku ps:scale worker=1
heroku config:set PAUSE_SCHEDULER=false
