import logging
import os
import re
import subprocess

import coloredlogs
import requests

def setupLogging(logname=__name__, level=logging.DEBUG, logFormat='%(asctime)s [%(levelname)s] %(message)s'):
    myLog = logging.getLogger(logname)
    consoleHandler = logging.StreamHandler()
    consoleHandler.setLevel(level)
    myFormat = logging.Formatter(logFormat)
    consoleHandler.setFormatter(myFormat)
    myLog.addHandler(consoleHandler)

    myLog.setLevel(level)

    coloredlogs.install(level=logging.getLevelName(level), logger=myLog, fmt=logFormat)

    return myLog

def downloadFile(url, folder=None, filename=None):
    with requests.get(url, allow_redirects=True, stream=True) as myReq:
        myReq.raise_for_status()
        if not filename:
            contentDisposition = myReq.headers.get('Content-Disposition')
            if not contentDisposition:
                filename = url.rsplit('/', 1)[1]
            else:
                filename = re.findall('filename=(.+)', contentDisposition)
        if folder:
            if not os.path.exists(folder):
                os.mkdir(folder)
            filename = os.path.join(folder, filename)

        with open(filename, 'wb', ) as outFile:
            for chunk in myReq.iter_content(chunk_size=8192):
                if chunk: # filter out keep-alive new chunk
                    outFile.write(chunk)

    return filename

def resetPermissions(folderName):
    for root, dirs, files in os.walk(folderName):
        for dRef in dirs:
            os.chmod(os.path.join(root, dRef), 0o0755)
        for fRef in files:
            os.chmod(os.path.join(root, fRef), 0o0644)

def unzipFile(filename, targetFolder):
   command = ['unzip', filename, '-d', targetFolder]
   myProc = subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
   if myProc.returncode >= 2:
       raise RuntimeError('Unzip of {} -> {} failed.'.format(filename, targetFolder))

def syncFolder(srcFolder, dstFolder, destRsyncPath=''):
    command = ['rsync']
    if destRsyncPath:
        command += ['--rsync-path', destRsyncPath]
    command += ['-avuhP', '--delete', '-e', 'ssh', srcFolder, dstFolder]
    myProc = subprocess.run(command, stderr=subprocess.STDOUT)
    if myProc.returncode != 0:
        raise RuntimeError('Folder Sync {} -> {} failed'.format(srcFolder, dstFolder))

def updateConfig(filename, data):
    with open(filename, 'r', encoding='utf-8') as confFile:
        confLines = confFile.readlines()

    # Used to keep track of fields that already exist
    keyMap = {}

    for iRef in enumerate(confLines):
        if '=' in iRef[1]:
            key, value = re.findall('(.+)=(.+)', iRef[1], re.DOTALL)[0]
            if key in data:
                confLines[iRef[0]] = "{}={}\n".format(key, data.get(key))
                keyMap[key] = data.get(key)
            else:
                keyMap[key] = value


    with open(filename, 'w', encoding='utf-8') as confFile:
        confFile.writelines(confLines)

        # adding any fields that didn't exist previously
        for key, value in data.items():
            if not key in keyMap:
                confFile.write("{}={}\n".format(key, value))


def createEULA(folder):
    myFilename = os.path.join(folder, 'eula.txt')

    eulaStr = '''#By changing the setting below to TRUE you are indicating your agreement to our EULA (https://account.mojang.com/documents/minecraft_eula).
#Mon Sep 29 23:27:36 UTC 2014
eula=true'''

    with open(myFilename, 'w', encoding='utf-8') as eulaFile:
        eulaFile.write(eulaStr)

def getServerProperies(targetFolder):
    pFilename = os.path.join(targetFolder, 'server.properties')
    retData = {}
    with open(pFilename, 'r', encoding='utf-8') as pFile:
        for lRef in pFile.readlines():
            myLine = lRef.rstrip('\n')
            pos = myLine.find('=')
            if pos >= 0:
                key = myLine[:pos]
                value = myLine[pos+1:]
                retData[key] = value

    return retData


if __name__ == '__main__':
    #myFilename = downloadFile('https://media.forgecdn.net/files/2744/435/Enigmatica2Server-1.69a.zip')
    #print(myFilename)

    # log = setupLogging()
    # log.info('Hi there')
    myData = getServerProperies('instances/enigmatica2')
    for dkey, dvalue in myData.items():
        print( dkey, '=', dvalue )
