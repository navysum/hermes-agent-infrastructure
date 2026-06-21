#!/bin/bash
# Fetch latest Whoop data and write to ~/whoop-sync/sync.log
cd /root/whoop-sync
python3 fetch_data.py 2>&1
