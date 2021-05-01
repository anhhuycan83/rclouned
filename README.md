# rclouned
A two-way cloud sync client using rclone. rclone + cloud + daemon = rclouned.

## The problem with rclone
rclone and especially subcommands like `rclone sync` assume one primary data source and can then modify a secondary data source to make it the same as the primary source (one-way sync).
It especially does not sync any changes on the secondary source to the primary source. In most cases, the primary source will be a local file system and the secondary source a remote cloud service. Therefore, rclone works well for backing up a local system to a remote but will only overwrite remote changes and not sync them.
A setup in which multiple computers (local file system) sync their data via a remote cloud service therefore does not work via rclone like it would using for example the official clients of Dropbox, OneDrive or Google Drive.
Using something like `rclone sync local remote && rclone sync remote local` is thinkable but poses some problems. Firstly, in the scenarios where a file is different locally and remotely, the remote changes would just be overwritten (even if they are newer). Secondly, deleting a file or creating a new file will always go wrong - in which way depends on the ordering in the command and whether sync is set to delete files (e.g. create new file on remote, sync local to remote with delete => file deleted; delete file locally, sync remote to local => file exists again).

## The approach
Before blindly syncing files, take a look at their modification times and then try to make "smart"-ish decisions about which files should be synced which way.
That works like this:
1. Run `rclone check`. That gives us all the differences between the local system and the remote.
2. For each difference, check the local file modification time, the remote modification time and the time of the last sync. Interpret these values using the table below.
3.  Run the actions using multiple `rclone` commands including `rclone copy` and `rclone delete`. As well as local commands like `mv` and `rm`.

| rclone check | comparison | interpretation | action |
|--|--|--|--|
| not on remote | local modtime after last sync | new local file | copy local file to remote |
| | local modtime before last sync | file deleted on remote | delete local file |
| not on local | remote modtime after last sync | new remote file | copy remote file to local |
| | remote modtime before last sync | file deleted on local | delete remote file |
| local and remote differ | local modtime after last sync and remote modtime before last sync | file modified on local | copy local file to remote |
| | local modtime before last sync and remote modtime after last sync | file modified on remote | copy remote file to local |
| | local and remote modtime before last sync | ??? (should not happen, probably a RC) | treat as below |
| | local and remote modtime after last sync | conflict, two unsynced modifications | copy remote file to local (rename local  `{,-conflict}`) |

## Issues by design
* For the initial file comparison, we rely on `rclone check`, which might not spot all modifications especially when not using hashes for comparisons but only modification time and file size (which is the default for most remote providers).
* Modification times are somewhat unreliable and can be manipulated.
* Open to Race Conditions when comparing modification times.
* To mitigate the first two issues, `rclouned`backs up files before overwriting and moves to trash instead of deleting. This can/will require (significant) additional storage. There is no automated garbage collection (yet).

## How to use
1. Download the `rclouned` script and put it somewhere where you can execute it (don't forget the executable-bit). In the following, we assume `rclouned` is accessible on `$PATH`.
2. Create the rclone remote using `rclone config`.
3. In your local sync folder, create a `.rclouned`subfolder and create a configuration file called `config.yaml`in it.
4. Modify the configuration file. See the example.
5. Run rclouned using `rclouned {localdir}`, for daemon mode add `-d`.
6. Check the logs for success.
