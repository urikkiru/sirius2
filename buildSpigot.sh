#!/usr/bin/env bash
curl -o BuildTools.jar https://hub.spigotmc.org/jenkins/job/BuildTools/lastSuccessfulBuild/artifact/target/BuildTools.jar
git config --global unset core.autocrlf
java -jar BuildTools.jar --rev 1.15.1