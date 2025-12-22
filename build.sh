#!/bin/bash
set -e  # Exit immediately if a command exits with a non-zero status

# Output colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${BLUE}=== Building YT-RSS Discovery ===${NC}"

# Function to show installation help
show_install_help() {
    echo -e "${YELLOW}Installation tips:${NC}"
    echo "  Debian/Ubuntu: sudo apt install python3 python3-venv python3-pip"
    echo "  Fedora:        sudo dnf install python3"
    echo "  Arch Linux:    sudo pacman -S python"
}

# 1. Check if Python exists
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}Error: Python 3 is required but not found.${NC}"
    show_install_help
    exit 1
fi

# 2. Check if venv module exists (some distros separate it)
if ! python3 -c "import venv" &> /dev/null; then
    echo -e "${RED}Error: Python venv module is missing.${NC}"
    show_install_help
    exit 1
fi

# 3. Check if source code exists
if [ ! -f "ytrss.py" ]; then
    echo -e "${RED}Error: Could not find ytrss.py. Run the script from the project directory.${NC}"
    exit 1
fi

# 4. Create temporary build environment
echo -e "${BLUE}> Creating temporary virtual environment (.build_venv)...${NC}"
rm -rf .build_venv
python3 -m venv .build_venv
source .build_venv/bin/activate

# 5. Install dependencies
echo -e "${BLUE}> Installing dependencies...${NC}"

# Ensure pip exists
if ! command -v pip &> /dev/null; then
    echo -e "${RED}Error: pip not found in the virtual environment.${NC}"
    show_install_help
    exit 1
fi

pip install --upgrade pip > /dev/null
pip install feedparser aiohttp simple-term-menu pyinstaller

# 6. Build binary with PyInstaller

echo -e "${BLUE}> Building binary with PyInstaller...${NC}"

pyinstaller --clean --onefile --name ytrss --add-data "KEYS.md:." --log-level ERROR ytrss.py



# 7. Clean up

echo -e "${BLUE}> Cleaning up build files...${NC}"

deactivate

rm -rf .build_venv

rm -rf build

rm -f ytrss.spec



echo -e "${GREEN}=== Build complete! ===${NC}"

echo -e "Your executable is here: ${GREEN}./dist/ytrss${NC}"

echo ""

echo "You can install it to your bin directory with:"

echo "  cp dist/ytrss ~/bin/"

echo "Or system-wide:"

echo "  sudo cp dist/ytrss /usr/local/bin/"