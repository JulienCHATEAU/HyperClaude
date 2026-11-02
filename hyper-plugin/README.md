# Plugin Hyper - HyperClaude (focus fenetre, L3)

Plugin compagnon qui met **la bonne fenetre Hyper au premier plan** quand on clique une
session dans le widget HyperClaude.

## Principe

1. Le widget ecrit un ordre de focus dans `~/.hyperclaude/focus.json` :
   `{ "shellPid": <pid du shell>, "tty": "ttysNNN", "ts": <epoch ms> }`.
2. Ce plugin (process principal de Hyper) surveille le fichier et cherche la fenetre dont
   une session node-pty a `pty.pid === shellPid` (repli : meme `tty` via `ps`).
3. Il met cette fenetre au premier plan (`show` + `focus` + `moveTop`).

Correlation par **pid de shell** : le zsh lance par node-pty (`pty.pid`) est le parent du
process `claude` ; le widget transmet ce pid (le `ppid` de `claude`). Robuste et sans
ambiguite (une session = une fenetre dans ce setup).

## Installation

```bash
# lier le plugin dans les plugins locaux de Hyper
mkdir -p ~/.hyper_plugins/local
ln -s ~/Documents/Perso/Projets/HyperClaude/hyper-plugin ~/.hyper_plugins/local/hyperclaude
```

Puis dans `~/.hyper.js`, ajouter `'hyperclaude'` a `localPlugins` :

```js
localPlugins: ['hyperclaude'],
```

Enfin, recharger Hyper : menu **Plugins > Update all now**, ou `Cmd+Shift+R`, ou redemarrer
Hyper.

## Verification / debug

- Journal : `~/.hyperclaude/plugin.log` (surveillance active, requetes recues, focus).
- Test manuel (remplacer le pid par un vrai pid de shell zsh d'un onglet) :

```bash
echo '{"shellPid": 12345, "ts": '"$(python3 -c 'import time;print(int(time.time()*1000))')"'}' \
  > ~/.hyperclaude/focus.json
```

La fenetre correspondante doit passer au premier plan.

## Limites

- Depend de l'API interne de Hyper (`win.sessions`, `session.pty.pid`) : non contractuelle,
  a re-verifier apres une mise a jour majeure de Hyper.
- Cas non nominal (tmux, SSH, `claude` imbrique) : le pid de shell ne correspond pas au
  `pty.pid` ; le focus retombe alors sur l'activation simple de Hyper (cote widget).
