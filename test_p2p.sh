#!/bin/bash

RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

echo "Creating test files..."
echo "This is test file 1" > file1.txt
echo "This is test file 2" > file2.txt
echo "This is test file 3" > file3.txt

echo -e "${RED}Cleaning up any existing processes...${NC}"
pkill -f "python3 tracker.py"
pkill -f "python3 peer.py"
sleep 2

echo -e "${GREEN}Starting tracker...${NC}"
gnome-terminal -- bash -c "python3 tracker.py 127.0.0.1:6771; read -p 'Press Enter to close...'" &
sleep 2

echo -e "${BLUE}Starting Peer1 (sharing file1.txt)...${NC}"
mkdir -p peer1_dir
cp file1.txt peer1_dir/
cd peer1_dir
gnome-terminal -- bash -c "python3 ../peer.py share file1.txt 127.0.0.1:6771 127.0.0.1:7001 Peer1; read -p 'Press Enter to close...'" &
cd ..
sleep 2

echo -e "${BLUE}Starting Peer2 (sharing file2.txt)...${NC}"
mkdir -p peer2_dir
cp file2.txt peer2_dir/
cd peer2_dir
gnome-terminal -- bash -c "python3 ../peer.py share file2.txt 127.0.0.1:6771 127.0.0.1:7002 Peer2; read -p 'Press Enter to close...'" &
cd ..
sleep 2

echo -e "${BLUE}Starting Peer3 (will download files)...${NC}"
mkdir -p peer3_dir
cd peer3_dir
gnome-terminal -- bash -c "python3 ../peer.py get file1.txt 127.0.0.1:6771 127.0.0.1:7003 Peer3; read -p 'Press Enter to close...'" &
cd ..
sleep 5

echo -e "${GREEN}Test Scenario 1: Peer3 downloading file1.txt from Peer1${NC}"
sleep 5

echo -e "${GREEN}Test Scenario 2: Peer3 trying to download non-existent file${NC}"
cd peer3_dir
gnome-terminal -- bash -c "python3 ../peer.py get nonexistent.txt 127.0.0.1:6771 127.0.0.1:7003 Peer3; read -p 'Press Enter to close...'" &
cd ..
sleep 5

echo -e "${GREEN}Test Scenario 3: Peer3 downloading file2.txt from Peer2${NC}"
cd peer3_dir
gnome-terminal -- bash -c "python3 ../peer.py get file2.txt 127.0.0.1:6771 127.0.0.1:7003 Peer3; read -p 'Press Enter to close...'" &
cd ..
sleep 5

echo -e "${GREEN}Test Scenario 4: Peer1 disconnecting${NC}"
pkill -f "python3.*Peer1"
sleep 5

echo -e "${GREEN}Test Scenario 5: New download of file1.txt after Peer1 disconnected${NC}"
mkdir -p peer4_dir
cd peer4_dir
gnome-terminal -- bash -c "python3 ../peer.py get file1.txt 127.0.0.1:6771 127.0.0.1:7004 Peer4; read -p 'Press Enter to close...'" &
cd ..
sleep 5

echo -e "${GREEN}Test completed! Each component is running in its own terminal window.${NC}"
echo -e "${BLUE}Please check the individual terminal windows for logs.${NC}"
echo -e "${RED}Press Ctrl+C in each terminal to close them when done testing.${NC}"