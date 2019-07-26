#!/usr/bin/env python3
import datetime
import glob
import os
import shutil
import subprocess

import docker
import fire
from jinja2 import Template
from mcrcon import MCRcon
import yaml

from core_utils import (
    downloadFile, setupLogging, unzipFile, resetPermissions, updateConfig, createEULA, getServerProperies, syncFolder
)


log = setupLogging()


class Config:
    def __init__(self):
        self.configFolder = os.path.join(os.getcwd(), "config")
        self.instanceFolder = os.path.join(os.getcwd(), "instances")
        self.workingDir = os.getcwd()
        self.imageName = 'sirius2/server'
        self.imageVersion = '1.0'
        self.mountpoint = '/minecraft'


class Core:
    def __init__(self):
        self.data = {}

        self.config = Config()
        # self.myDocker = DockerUtils()
        self.client = docker.from_env()

        self.__loadDefinitions()

        if not os.path.exists(self.config.instanceFolder):
            os.mkdir(self.config.instanceFolder)

    def __loadDefinitions(self):
        configList = glob.glob(os.path.join(self.config.configFolder, "*.yaml"))

        for cRef in configList:
            with open(cRef, "r", encoding='utf-8') as confFile:
                cData = yaml.load(confFile, Loader=yaml.FullLoader)
                self.data[os.path.splitext(os.path.basename(cRef))[0]] = cData

    def help(self):
        print('Help placeholder')

    def build(self, nocache=False):
        log.info('Building docker image')

        targetFolder = self.config.workingDir
        templateFilename = os.path.join(targetFolder, 'Dockerfile.template')
        with open(templateFilename, 'r', encoding='utf-8') as tFile:
            tData = tFile.read()
            myTemplate = Template(tData)
            outputData = myTemplate.render(
                {
                    'gid': os.getgid(),
                    'uid': os.getuid()
                }
            )
            with open(os.path.join(targetFolder, 'Dockerfile'), 'w', encoding='utf-8') as outFile:
                outFile.write(outputData)

        self.client.images.build(path=targetFolder, nocache=nocache, tag='{}:{}'.format(
            self.config.imageName,
            self.config.imageVersion
        ))
        self.client.images.build(path=targetFolder, nocache=nocache, tag='{}:latest'.format(self.config.imageName))

    def download(self, name):
        url = self.data[name]['url']
        instanceFolder = os.path.join(self.config.instanceFolder, name)

        if os.path.exists(instanceFolder):
            raise FileExistsError('Instance folder "{}" already exists'.format(instanceFolder))

        os.mkdir(instanceFolder)

        log.info('[{}] Downloading {}'.format(name, url))
        myFilename = downloadFile(url, instanceFolder)

        log.info('Download Complete, extracting: {}'.format(myFilename))
        unzipFile(myFilename, instanceFolder)

        log.info('Resetting file permissions')
        resetPermissions(instanceFolder)

        os.chmod(os.path.join(instanceFolder, self.data[name]['entrypoint']), 0o0755)

    def configure(self, name):
        instanceFolder = os.path.join(self.config.instanceFolder, name)
        for filename, data in self.data[name]['configs'].items():
            log.info('Patching {}'.format(filename))

            fullFilename = os.path.join(instanceFolder, filename)
            updateConfig(fullFilename, data)

        log.info('Creating eula.txt')
        createEULA(instanceFolder)

    def start(self, name):
        log.info('Starting {}'.format(name))

        instanceFolder = os.path.join(self.config.instanceFolder, name)
        startCommand = os.path.join(self.config.mountpoint, self.data[name]['entrypoint'])
        port = self.data[name]['port']
        rconport = self.data[name].get('rconport')
        print(startCommand)
        self.client.containers.prune()

        portmap = {
            '{}/tcp'.format(port): '{}'.format(port)
        }
        if rconport:
            portmap['{}/tcp'.format(rconport)] = rconport

        self.client.containers.run(
            image='{}:{}'.format(self.config.imageName, self.config.imageVersion),
            command=startCommand,
            name=name,
            volumes={
                instanceFolder: {
                    'bind': self.config.mountpoint,
                    'mode': 'rw'
                }
            },
            ports=portmap,
            user='minecraft',
            working_dir=self.config.mountpoint,
            detach=True,
            stdin_open=True,
            tty=True
        )

    def stop(self, name):
        pass

    def destroy(self, name, confirm=False):
        if not name in self.data:
            raise ValueError('{} not a valid instance name'.format(name))
        myInstanceFolder = os.path.join(self.config.instanceFolder, name)
        log.info('Destroying instance {} {}'.format(name, myInstanceFolder))

        if not confirm:
            log.warning('Dry run. Use "destroy --confirm=True" if you\'re really sure. All instance data will be deleted.')
            return

        # TODO stop any existing docker instance first

        # This is required because sometimes mod pack config files have incorrect *nix permissions. This leads to weird
        # scenarios where you don't have list access to the file/folder and therefore cannot delete it.
        resetPermissions(myInstanceFolder)

        if os.path.exists(myInstanceFolder):
            shutil.rmtree(myInstanceFolder)

    def install(self, name):
        self.build()
        self.download(name)
        self.configure(name)
        #self.start(name)

    def upgrade(self, name):
        myInstanceFolder = os.path.join(self.config.instanceFolder, name)
        upgradeList = self.data[name]['upgradeList']

        zipList = glob.glob(os.path.join(myInstanceFolder, '*.zip'))
        if len(zipList) != 1:
            raise FileNotFoundError('Unable to discern current instance name and version from the .zip file.')

        baseName = os.path.basename(zipList[0])
        rotateName = os.path.splitext(baseName)[0]
        timestamp = datetime.datetime.strftime(datetime.datetime.now(), "%m-%d-%Y_%H.%M.%S")
        oldFolderPath = os.path.join(self.config.instanceFolder, '{}_{}'.format(rotateName, timestamp))
        log.info('Renaming {} -> {}'.format(myInstanceFolder, oldFolderPath))
        shutil.move(myInstanceFolder, oldFolderPath)

        self.download(name)
        self.configure(name)

        for uRef in upgradeList:
            mySrc = os.path.join(oldFolderPath, uRef)
            if not os.path.exists(mySrc):
                raise FileNotFoundError(mySrc)
            myDst = os.path.join(myInstanceFolder, uRef)
            log.info("Copying {} -> {}".format(mySrc, myDst))
            if os.path.isdir(mySrc):
                shutil.copytree(mySrc, myDst)
            else:
                shutil.copy(mySrc, myDst)

        log.info('Upgrade complete')

    def exec(self, name, commStr):
        if not commStr.startswith('/'):
            commStr = '/' + commStr
        instanceFolder = os.path.join(self.config.instanceFolder, name)
        myProps = getServerProperies(instanceFolder)

        if myProps.get('enable-rcon') == 'true':
            with MCRcon(host='localhost', password=myProps.get('rcon.password'), port=int(myProps.get('rcon.port'))) as mcr:
                resp = mcr.command(commStr)
                log.info(resp)
        else:
            log.error('rcon disabled for this server instance')

    def syncbackups(self, name, dest, remoteRsyncPath=None):
        srcFolder = os.path.join(self.config.instanceFolder, name, 'backups')
        dstFolder = os.path.join(dest, name)
        log.info('Syncing Backups {} -> {}'.format(srcFolder, dstFolder))
        syncFolder(srcFolder, dstFolder, remoteRsyncPath)


if __name__ == '__main__':
    myCore = Core()
    fire.Fire(myCore)
