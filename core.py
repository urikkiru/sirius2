#!/usr/bin/env python3
import datetime
from distutils.dir_util import copy_tree
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
    downloadFile,
    setupLogging,
    unzipFile,
    resetPermissions,
    updateConfig,
    updateYaml,
    createEULA,
    getServerProperies,
    syncFolder,
    convertFileToUnixLineEndings,
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
        instanceFolder = os.path.join(self.config.instanceFolder, name)
        if os.path.exists(instanceFolder):
            raise FileExistsError('Instance folder "{}" already exists'.format(instanceFolder))
        os.mkdir(instanceFolder)

        patchData = self.data[name].get('patch')
        if patchData:
            # log.info('Patch data found, copying previous folder')
            # copy_tree(oldFolderPath, instanceFolder)
            log.info('Patch data found')

            patchURL = patchData['url']
            baseFolder = patchData.get('basefolder')
            patchFolder = os.path.join(instanceFolder, 'patches')

            log.info('[{}] Downloading Patch {} -> {}'.format(name, patchURL, patchFolder))
            patchFilename = downloadFile(patchURL, folder=patchFolder)
            unzipFile(patchFilename, patchFolder)

            realPatchFolder = os.path.join(patchFolder, baseFolder)
            log.info('[{}] Moving Patch Files {} -> {}'.format(name, os.path.join(realPatchFolder, baseFolder), instanceFolder))
            copy_tree(realPatchFolder, instanceFolder)
        else:
            url = self.data[name]['url']

            log.info('[{}] Downloading {}'.format(name, url))
            myFilename = downloadFile(url, folder=instanceFolder)

            log.info('Download Complete, extracting: {}'.format(myFilename))
            unzipFile(myFilename, instanceFolder)

    def configure(self, name):
        instanceFolder = os.path.join(self.config.instanceFolder, name)

        propsFilepath = os.path.join(instanceFolder, 'server.properties')
        if not os.path.exists(propsFilepath):
            shutil.copy('server.properties.template', propsFilepath)

        for filename, data in self.data[name]['configs'].items():
            log.info('Patching config {}'.format(filename))

            fullFilename = os.path.join(instanceFolder, filename)
            updateConfig(fullFilename, data)

        yamlData = self.data[name].get('yamls')
        if yamlData:
            for filename in yamlData:
                data = yamlData[filename]
                log.info('Patching yaml {}'.format(filename))

                fullFilename = os.path.join(instanceFolder, filename)
                updateYaml(fullFilename, data)

        log.info('Creating eula.txt')
        createEULA(instanceFolder)

        log.info('Resetting file permissions')
        resetPermissions(instanceFolder)

        os.chmod(os.path.join(instanceFolder, self.data[name]['entrypoint']), 0o0755)

    def start(self, name):
        log.info('Starting {}'.format(name))

        instanceFolder = os.path.join(self.config.instanceFolder, name)
        startCommand = os.path.join(self.config.mountpoint, self.data[name]['entrypoint'])
        convertFileToUnixLineEndings(os.path.join(instanceFolder, self.data[name]['entrypoint']))
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
        self.install_mods(name)
        self.configure(name)
        #self.start(name)

    def install_mods(self, name):
        instanceFolder = os.path.join(self.config.instanceFolder, name)
        disableList = self.data[name]['modsList']['disable']
        modsList = self.data[name]['modsList']['install']

        if disableList:
            print('Disabling Mods:')
            for dRef in disableList:
                modFilename = os.path.join(instanceFolder, 'mods', dRef)
                disabledFilename = modFilename + '.disabled'
                if os.path.exists(modFilename):
                    log.info('-- Renaming {} to {}'.format(modFilename, disabledFilename))
                    os.rename(modFilename, disabledFilename)

        if modsList:
            print('Installing Mods:')
            for mRef in modsList:
                log.info('-- {}'.format(mRef))
                downloadFile(mRef, os.path.join(instanceFolder, 'mods'))

    def upgrade(self, name):
        instanceFolder = os.path.join(self.config.instanceFolder, name)
        upgradeList = self.data[name]['upgradeList']

        rotateName = name
        timestamp = datetime.datetime.strftime(datetime.datetime.now(), "%m-%d-%Y_%H.%M.%S")
        oldFolderPath = os.path.join(self.config.instanceFolder, '{}_{}'.format(rotateName, timestamp))
        log.info('Renaming {} -> {}'.format(instanceFolder, oldFolderPath))
        shutil.move(instanceFolder, oldFolderPath)

        self.download(name)
        self.install_mods(name)

        for uRef in upgradeList:
            mySrc = os.path.join(oldFolderPath, uRef)
            if not os.path.exists(mySrc):
                raise FileNotFoundError(mySrc)
            myDst = os.path.join(instanceFolder, uRef)
            log.info("Copying {} -> {}".format(mySrc, myDst))
            if os.path.isdir(mySrc):
                shutil.copytree(mySrc, myDst)
            else:
                shutil.copy(mySrc, myDst)

        self.configure(name)

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
