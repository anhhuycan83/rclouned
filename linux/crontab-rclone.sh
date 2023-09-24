#! /bin/bash
rclone_macos_log=/Users/huy/rclone.macos.log
/usr/local/bin/python3 /Users/huy/working/refer/rclouned/sync.py /Users/huy/sync > $rclone_macos_log 2>&1
cp $rclone_macos_log /Users/huy/sync/logs/macos
