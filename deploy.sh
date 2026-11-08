#!/bin/sh
# Deploy the COMMITTED build (HEAD) to the Halo; untracked assets are copied, half-edited tracked files never are.
# Static files are live on reload; pass --restart when Python changed.
set -e
cd "$(dirname "$0")"
H=pablo@10.103.1.11; DEST=armstrong-claude/blackjack
rsync -a --exclude .git --exclude __pycache__ --exclude .claude --exclude '*.py' --exclude 'tabletop/*.js' --exclude 'tabletop/*.css' --exclude 'tabletop/*.html' ./ $H:$DEST/
git archive HEAD | ssh $H "tar -x -C $DEST"
echo "deployed $(git rev-parse --short HEAD)"
[ "$1" = "--restart" ] && ssh $H 'systemctl --user restart armstrong-blackjack-camera.service armstrong-blackjack-tabletop.service && sleep 3 && systemctl --user is-active armstrong-blackjack-camera.service armstrong-blackjack-tabletop.service'
exit 0
