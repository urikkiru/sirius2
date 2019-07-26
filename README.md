# sirius2
Modded Minecraft Server Management

Here's an example "config/enigmatica2.yaml" file

```yaml
#url: "https://media.forgecdn.net/files/2744/435/Enigmatica2Server-1.69a.zip"
url: "https://media.forgecdn.net/files/2745/593/Enigmatica2Server-1.69b.zip"
entrypoint: "ServerStartLinux.sh"
port: &port 25572

configs:
  settings.cfg:
    MAX_RAM: "8G; "
  server.properties:
    server-port: *port
    difficulty: 2
    pvp: "false"
    motd: "Jarvis presents Enigmatica 2, best with bdcraft.net (Sphax) textures!"

upgradeList:
  - world
  - ops.json
```