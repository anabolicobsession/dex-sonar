#!/bin/bash

heroku config:set $(tr '\n' ' ' <<< "$(cat .env)")
git push $1 heroku

heroku ps:scale worker=1
heroku config:set PAUSE_SCHEDULER=true
