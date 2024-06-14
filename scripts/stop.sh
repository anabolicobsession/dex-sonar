#!/bin/bash

heroku ps:scale worker=0
heroku config:set PAUSE_SCHEDULER=false
