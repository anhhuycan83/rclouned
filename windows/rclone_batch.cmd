set local=d:/huy/onedrive/sync
set remote=gdrive:sync
set rclone_Config_File=C:\Users\phamquochuy\AppData\Roaming\rclone\rclone.conf
set output_log_file=d:\huy\tool\rclone-cty.log
set output_log_file_sync=d:\huy\onedrive\sync\logs\tma\rclone-cty.log

c:\Python310\python.exe d:/huy/tool/sync.py %local% 1> %output_log_file% 2>&1
cp %output_log_file% %output_log_file_sync%