import feedparser
import subprocess
import sys
import os
import shutil
import sqlite3
import asyncio
import aiohttp
import webbrowser
import xml.etree.ElementTree as ET
from datetime import datetime
from simple_term_menu import TerminalMenu

# Configuration
QUICKTUBE_CMD = "quicktube"
CONFIG_DIR = os.path.expanduser("~/.config/ytrss")
OPML_FILE = os.path.join(CONFIG_DIR, "ytRss.opml")
DB_FILE = os.path.join(CONFIG_DIR, "ytrss.db")
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/90.0.4430.212 Safari/537.36"

# Create config directory if it doesn't exist
os.makedirs(CONFIG_DIR, exist_ok=True)

# Global state
duration_cache = {}
SHOW_SHORTS = True  # Default: Show shorts

def clean_title(text):
    """Cleans the title from characters that might cause issues in the terminal."""
    if not text: return ""
    text = text.replace('\u3164', ' ').replace('\u115f', ' ').replace('\u1160', ' ')
    text = "".join(c if c.isprintable() else " " for c in text)
    text = " ".join(text.split())
    return text

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS seen_videos
                 (video_id TEXT PRIMARY KEY, title TEXT, seen_date TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS video_metadata
                 (video_id TEXT PRIMARY KEY, duration TEXT)''')
    
    # New tables for playlists
    c.execute('''CREATE TABLE IF NOT EXISTS playlists (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    is_system_list BOOLEAN DEFAULT 0
                 )''')
    c.execute('''CREATE TABLE IF NOT EXISTS videos (
                    video_id TEXT PRIMARY KEY,
                    title TEXT,
                    channel TEXT,
                    url TEXT,
                    duration TEXT,
                    is_shorts BOOLEAN,
                    published_date TEXT,
                    first_seen TEXT DEFAULT CURRENT_TIMESTAMP
                 )''')
    c.execute('''CREATE TABLE IF NOT EXISTS playlist_items (
                    playlist_id INTEGER NOT NULL,
                    video_id TEXT NOT NULL,
                    added_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (playlist_id) REFERENCES playlists(id) ON DELETE CASCADE,
                    FOREIGN KEY (video_id) REFERENCES videos(video_id) ON DELETE CASCADE,
                    PRIMARY KEY (playlist_id, video_id)
                 )''')
    
    # Ensure "Watch Later" exists
    c.execute("INSERT OR IGNORE INTO playlists (name, is_system_list) VALUES (?, ?)", ("Watch Later", 1))
    
    conn.commit()
    conn.close()

def mark_as_seen(video_id, title):
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("INSERT OR IGNORE INTO seen_videos (video_id, title, seen_date) VALUES (?, ?, ?)",
                  (video_id, title, datetime.now().isoformat()))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Database error: {e}")

def mark_all_as_seen(videos):
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        now = datetime.now().isoformat()
        # Create a list of tuples for executemany
        data = [(v['id'], v['title'], now) for v in videos]
        c.executemany("INSERT OR IGNORE INTO seen_videos (video_id, title, seen_date) VALUES (?, ?, ?)", data)
        conn.commit()
        conn.close()
        print(f"Marked {len(videos)} videos as seen.")
    except Exception as e:
        print(f"Database error: {e}")

def get_seen_videos():
    seen = set()
    if not os.path.exists(DB_FILE):
        return seen
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT video_id FROM seen_videos")
        for row in c.fetchall():
            seen.add(row[0])
        conn.close()
    except:
        pass
    return seen

def get_cached_metadata():
    metadata = {}
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT video_id, duration FROM video_metadata")
        for row in c.fetchall():
            metadata[row[0]] = row[1]
        conn.close()
    except:
        pass
    return metadata

def save_metadata(video_id, duration):
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO video_metadata (video_id, duration) VALUES (?, ?)",
                  (video_id, duration))
        conn.commit()
        conn.close()
    except:
        pass

def add_to_playlist(playlist_name, video):
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        
        # 1. Get playlist id
        c.execute("SELECT id FROM playlists WHERE name = ?", (playlist_name,))
        row = c.fetchone()
        if not row: return False
        playlist_id = row[0]
        
        # 2. Add video to 'videos' table if not exists
        # Handle 'published' format (struct_time or string)
        pub_date = ""
        if video.get('published'):
            if isinstance(video['published'], (list, tuple)):
                pub_date = datetime(*video['published'][:6]).isoformat()
            else:
                pub_date = str(video['published'])

        c.execute('''INSERT OR REPLACE INTO videos (video_id, title, channel, url, duration, is_shorts, published_date)
                     VALUES (?, ?, ?, ?, ?, ?, ?)''',
                  (video['id'], video['title'], video.get('channel'), video['link'], 
                   video.get('duration'), video.get('is_shorts', False), pub_date))
        
        # 3. Link video to playlist
        c.execute("INSERT OR IGNORE INTO playlist_items (playlist_id, video_id) VALUES (?, ?)",
                  (playlist_id, video['id']))
        
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"Error adding to playlist: {e}")
        return False

def get_playlist_videos(playlist_name):
    videos = []
    try:
        conn = sqlite3.connect(DB_FILE)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        
        c.execute('''SELECT v.* FROM videos v
                     JOIN playlist_items pi ON v.video_id = pi.video_id
                     JOIN playlists p ON pi.playlist_id = p.id
                     WHERE p.name = ?
                     ORDER BY pi.added_at DESC''', (playlist_name,))
        
        rows = c.fetchall()
        for row in rows:
            videos.append({
                'id': row['video_id'],
                'title': row['title'],
                'link': row['url'],
                'channel': row['channel'],
                'duration': row['duration'],
                'is_shorts': bool(row['is_shorts']),
                'published': row['published_date'],
                'is_seen': False # Will be updated in show_playlist_ui or main
            })
        conn.close()
    except Exception as e:
        print(f"Error getting playlist: {e}")
    return videos

def remove_from_playlist(playlist_name, video_id):
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute('''DELETE FROM playlist_items 
                     WHERE video_id = ? AND playlist_id = (SELECT id FROM playlists WHERE name = ?)''',
                  (video_id, playlist_name))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"Error removing from playlist: {e}")
        return False

async def get_video_duration(video_url, video_id):
    if video_id in duration_cache and duration_cache[video_id] != "??:??":
        return duration_cache[video_id]
    
    try:
        proc = await asyncio.create_subprocess_exec(
            "yt-dlp", "--get-duration", video_url,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL
        )
        stdout, _ = await proc.communicate()
        
        if stdout:
            duration = stdout.decode().strip()
            if ':' in duration or duration.isdigit():
                if duration.isdigit():
                    duration = f"0:{duration.zfill(2)}"
                
                duration_cache[video_id] = duration
                save_metadata(video_id, duration)
                return duration
    except Exception:
        pass
    
    return "??:??"

def load_feeds_from_opml():
    if not os.path.exists(OPML_FILE):
        return []
    urls = []
    try:
        tree = ET.parse(OPML_FILE)
        root = tree.getroot()
        for outline in root.findall(".//outline"):
            url = outline.get('xmlUrl')
            if url:
                urls.append(url)
    except Exception as e:
        print(f"Error reading OPML: {e}")
    return urls

def add_feed_to_opml(url):
    print(f"Verifying link: {url} ...")
    try:
        d = feedparser.parse(url, agent=USER_AGENT)
        channel_title = d.feed.get('title', 'Unknown Channel')
    except Exception as e:
        print(f"Could not verify URL: {e}")
        return

    try:
        if os.path.exists(OPML_FILE):
            tree = ET.parse(OPML_FILE)
            root = tree.getroot()
            body = root.find('body')
        else:
            root = ET.Element('opml', version="1.0")
            ET.SubElement(root, 'head')
            body = ET.SubElement(root, 'body')
            tree = ET.ElementTree(root)

        ET.SubElement(body, 'outline', {
            'text': channel_title,
            'title': channel_title,
            'type': 'rss',
            'xmlUrl': url
        })
        tree.write(OPML_FILE, encoding='UTF-8', xml_declaration=True)
        print(f"Added: {channel_title}")
    except Exception as e:
        print(f"Could not save: {e}")

def remove_channel_ui():
    if not os.path.exists(OPML_FILE): return
    tree = ET.parse(OPML_FILE)
    root = tree.getroot()
    body = root.find('body')
    outlines = body.findall('outline')
    
    titles = [node.get('title') or node.get('text') or "Unknown" for node in outlines]
    titles.append("[Cancel]")
    
    menu = TerminalMenu(titles, title="Select channel to remove:")
    idx = menu.show()
    
    if idx is not None and idx < len(outlines):
        body.remove(outlines[idx])
        tree.write(OPML_FILE, encoding='UTF-8', xml_declaration=True)
        print("Channel removed.")

def get_resource_path(relative_path):
    """Get absolute path to resource, works for dev and for PyInstaller"""
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.dirname(os.path.abspath(__file__))

    return os.path.join(base_path, relative_path)

def show_help():
    help_file = get_resource_path("KEYS.md")
    if os.path.exists(help_file):
        try:
            with open(help_file, 'r') as f:
                content = f.read()
            # Simple pager using less if available, otherwise print
            if shutil.which("less"):
                 subprocess.run(["less", help_file])
            else:
                print("\n" + content + "\n")
                input("Press Enter to continue...")
        except Exception as e:
            print(f"Error showing help: {e}")
            input("Press Enter...")
    else:
        print("Help file KEYS.md not found.")
        input("Press Enter...")

async def fetch_feed(session, url):
    try:
        async with session.get(url, headers={"User-Agent": USER_AGENT}) as response:
            if response.status == 200:
                return await response.text()
    except:
        return None

async def show_video_menu(videos, playlist_name=None):
    global SHOW_SHORTS

    if not SHOW_SHORTS:
        videos = [v for v in videos if not v.get('is_shorts')]
        if not videos:
            print("No videos to show (Shorts are hidden).")
            await asyncio.sleep(1.5)
            return

    to_fetch = [v for v in videos[:40] if v['duration'] == "??:??"]
    
    if to_fetch:
        print(f"Fetching metadata for {len(to_fetch)} videos...")
        sem = asyncio.Semaphore(5)
        
        async def fetch_and_update(v):
            async with sem:
                dur = await get_video_duration(v['link'], v['id'])
                v['duration'] = dur
                if dur != "??:??":
                    try:
                        parts = dur.split(':')
                        if len(parts) == 2:
                            m, s = int(parts[0]), int(parts[1])
                            if m == 0 or (m == 1 and s == 0):
                                v['is_shorts'] = True
                    except: pass

        await asyncio.gather(*(fetch_and_update(v) for v in to_fetch))
        
        if not SHOW_SHORTS:
            videos = [v for v in videos if not v.get('is_shorts')]
            if not videos:
                print("All videos were Shorts and were filtered out.")
                await asyncio.sleep(1.5)
                return

    current_cursor_index = 0
    while True:
        menu_entries = []
        for v in videos:
            # Handle date format (RSS struct_time vs DB string)
            if isinstance(v['published'], str):
                try:
                    dt_obj = datetime.fromisoformat(v['published'])
                    dt = dt_obj.strftime("%m-%d %H:%M")
                except:
                    dt = "??-?? ??:??"
            else:
                try:
                    dt = datetime(*v['published'][:6]).strftime("%m-%d %H:%M")
                except:
                    dt = "??-?? ??:??"

            seen_mark = "✔" if v['is_seen'] else " "
            shorts_mark = "[SHORTS] " if v.get('is_shorts') else ""
            duration = v.get('duration', '??:??')
            
            safe_title = clean_title(v['title'])
            
            entry = f"[{seen_mark}] {dt}  {duration:<6}  {v['channel'][:12]:<12}  {shorts_mark}{safe_title}"
            menu_entries.append(entry)
        
        menu_entries.append("[Go back]")
        
        title_suffix = "(Shorts hidden)" if not SHOW_SHORTS else ""
        menu_title = f"Select video {title_suffix} (Press '/' to search, 'l' for Watch Later, 'b' for Browser)"
        if playlist_name:
             menu_title += ", 'd' to remove"

        menu = TerminalMenu(
            menu_entries, 
            title=menu_title,
            search_key="/",
            cursor_index=current_cursor_index,
            accept_keys=["enter", "l", "d", "b"]
        )
        idx = menu.show()
        
        if idx is None or idx == len(videos):
            break
        
        # Preserve cursor position
        current_cursor_index = idx
        video = videos[idx]
        key = menu.chosen_accept_key

        if key == 'b':
            print(f"Opening in browser: {video['title']}")
            webbrowser.open(video['link'])
            mark_as_seen(video['id'], video['title'])
            video['is_seen'] = True
            await asyncio.sleep(0.5)
            continue

        if key == 'l':
            if add_to_playlist("Watch Later", video):
                print(f"Added '{video['title'][:30]}...' to Watch Later.")
            else:
                print("Failed to add to Watch Later.")
            await asyncio.sleep(0.5)
            continue
            
        if key == 'd' and playlist_name:
            if remove_from_playlist(playlist_name, video['id']):
                print("Removed from playlist.")
                del videos[idx]
                if not videos: break # List empty
                if current_cursor_index >= len(videos):
                    current_cursor_index = len(videos) - 1
            else:
                print("Could not remove.")
            await asyncio.sleep(0.5)
            continue

        # Enter = Play
        mark_as_seen(video['id'], video['title'])
        video['is_seen'] = True
        
        print(f"Starting QuickTube for: {video['title']}")
        try:
            subprocess.run(["wl-copy", video['link']])
            subprocess.run([QUICKTUBE_CMD])
        except Exception as e:
            print(f"Error launching: {e}")

async def main_async():
    global duration_cache, SHOW_SHORTS
    init_db()
    duration_cache = get_cached_metadata()
    
    # Main loop to allow refreshing feeds
    while True:
        feeds = load_feeds_from_opml()
        seen_ids = get_seen_videos()
        
        if not feeds:
            print("\nNo channels found. [a] Add channel.")
        
        all_videos_by_channel = {}
        all_videos_flat = []

        print("Fetching feeds...")
        async with aiohttp.ClientSession() as session:
            tasks = [fetch_feed(session, url) for url in feeds]
            results = await asyncio.gather(*tasks)

        for xml_data in results:
            if not xml_data: continue
            d = feedparser.parse(xml_data)
            ch_name = d.feed.get('title', 'Unknown')
            
            ch_videos = []
            for entry in d.entries:
                vid_id = entry.get('id', entry.link)
                title = entry.title
                
                is_shorts = "#shorts" in title.lower() or "#shorts" in entry.get('summary', '').lower()
                    
                v = {
                    'id': vid_id,
                    'title': title,
                    'link': entry.link,
                    'published': entry.get('published_parsed'),
                    'channel': ch_name,
                    'is_seen': vid_id in seen_ids,
                    'is_shorts': is_shorts,
                    'duration': duration_cache.get(vid_id, "??:??")
                }
                
                if v['duration'] != "??:??":
                     try:
                        parts = v['duration'].split(':')
                        if len(parts) == 2:
                            m, s = int(parts[0]), int(parts[1])
                            if m == 0 or (m == 1 and s == 0):
                                v['is_shorts'] = True
                                is_shorts = True
                     except: pass

                if v['published']:
                    ch_videos.append(v)
                    all_videos_flat.append(v)
            
            all_videos_by_channel[ch_name] = ch_videos
        
        all_videos_flat.sort(key=lambda x: x['published'], reverse=True)

        # Menu logic
        should_refresh = False
        
        while not should_refresh:
            # Update unread count if we marked things as seen
            
            channel_names = sorted(all_videos_by_channel.keys())
            menu_options = []
            
            unread_total = len([v for v in all_videos_flat if not v['is_seen']])
            
            # --- PLAYLISTS ---
            wl_count = len(get_playlist_videos("Watch Later"))
            menu_options.append("--- PLAYLISTS ---")
            menu_options.append(f"[1] Watch Later ({wl_count})")

            menu_options.append(f"--- ALL VIDEOS ({unread_total} new) ---")
            
            for name in channel_names:
                unread_count = len([v for v in all_videos_by_channel[name] if not v['is_seen']])
                menu_options.append(f"{name} ({unread_count})")
                
            menu_options.extend([
                "-" * 30, 
                "[/] Search",
                "[r] Refresh feeds",
                "[a] Add channel", 
                "[d] Delete channel",
                "[m] Mark all as seen",
                "[?] Help",
                "[q] Quit"
            ])
            
            os.system('clear')
            main_menu = TerminalMenu(
                menu_options, 
                title=f"YT-RSS Discovery (Shorts: {'ON' if SHOW_SHORTS else 'OFF'})",
                search_key="/",
                accept_keys=["enter", "s"]
            )
            choice_idx = main_menu.show()
            
            if choice_idx is None: 
                sys.exit()
                
            if main_menu.chosen_accept_key == "s":
                SHOW_SHORTS = not SHOW_SHORTS
                continue

            choice_text = menu_options[choice_idx]
            
            if choice_text == "[q] Quit":
                sys.exit()
            elif choice_text == "[?] Help":
                show_help()
            elif choice_text == "[/] Search":
                continue # Selecting this just closes the menu, but search is handled by search_key
            elif choice_text.startswith("[1] Watch Later"):
                wl_videos = get_playlist_videos("Watch Later")
                if not wl_videos:
                    print("Watch Later is empty.")
                    await asyncio.sleep(1)
                else:
                    # Sync seen status
                    current_seen = get_seen_videos()
                    for v in wl_videos:
                        v['is_seen'] = v['id'] in current_seen
                    await show_video_menu(wl_videos, playlist_name="Watch Later")
            elif choice_text == "[r] Refresh feeds":
                should_refresh = True
                break
            elif choice_text == "[m] Mark all as seen":
                unseen = [v for v in all_videos_flat if not v['is_seen']]
                if unseen:
                    print(f"Marking {len(unseen)} videos as seen...")
                    mark_all_as_seen(unseen)
                    for v in unseen:
                        v['is_seen'] = True
                else:
                    print("No new videos to mark.")
                # Continue loop to refresh menu numbers
            elif choice_text == "[a] Add channel":
                url = await asyncio.to_thread(input, "Paste RSS URL: ")
                url = url.strip()
                if url: add_feed_to_opml(url)
                should_refresh = True # Update after add
                break
            elif choice_text == "[d] Delete channel":
                remove_channel_ui()
                should_refresh = True # Update after remove
                break
            elif "--- ALL VIDEOS" in choice_text:
                await show_video_menu(all_videos_flat[:50])
            elif choice_text.startswith("-"):
                continue
            else:
                found_name = None
                for name in channel_names:
                    if choice_text.startswith(name + " ("):
                        found_name = name
                        break
                
                if found_name and found_name in all_videos_by_channel:
                    videos = sorted(all_videos_by_channel[found_name], key=lambda x: x['published'], reverse=True)
                    await show_video_menu(videos)

if __name__ == "__main__":
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        pass
