import feedparser
import subprocess
import sys
import os
import sqlite3
import asyncio
import aiohttp
import xml.etree.ElementTree as ET
from datetime import datetime
from simple_term_menu import TerminalMenu

# Konfiguration
QUICKTUBE_CMD = "quicktube"
CONFIG_DIR = os.path.expanduser("~/.config/ytrss")
OPML_FILE = os.path.join(CONFIG_DIR, "ytRss.opml")
DB_FILE = os.path.join(CONFIG_DIR, "ytrss.db")
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/90.0.4430.212 Safari/537.36"

# Globalt tillstånd
duration_cache = {}
SHOW_SHORTS = True  # Standard: Visa shorts

def clean_title(text):
    """Rensar titeln från tecken som kan krångla i terminalen."""
    if not text: return ""
    # Ta bort "Hangul Filler" och andra osynliga tecken som ibland används för tomma titlar
    text = text.replace('\u3164', ' ').replace('\u115f', ' ').replace('\u1160', ' ')
    
    # Ersätt generella non-printable tecken
    text = "".join(c if c.isprintable() else " " for c in text)
    
    # Komprimera whitespace
    text = " ".join(text.split())
    
    return text

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS seen_videos
                 (video_id TEXT PRIMARY KEY, title TEXT, seen_date TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS video_metadata
                 (video_id TEXT PRIMARY KEY, duration TEXT)''')
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
        print(f"Databasfel: {e}")

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

async def get_video_duration(video_url, video_id):
    """Använder yt-dlp för att hämta längden på en video."""
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
        print(f"Fel vid läsning av OPML: {e}")
    return urls

def add_feed_to_opml(url):
    print(f"Verifierar länk: {url} ...")
    try:
        d = feedparser.parse(url, agent=USER_AGENT)
        channel_title = d.feed.get('title', 'Unknown Channel')
    except Exception as e:
        print(f"Kunde inte verifiera URL: {e}")
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
        print(f"Lade till: {channel_title}")
    except Exception as e:
        print(f"Kunde inte spara: {e}")

def remove_channel_ui():
    if not os.path.exists(OPML_FILE): return
    tree = ET.parse(OPML_FILE)
    root = tree.getroot()
    body = root.find('body')
    outlines = body.findall('outline')
    
    titles = [node.get('title') or node.get('text') or "Unknown" for node in outlines]
    titles.append("[Avbryt]")
    
    menu = TerminalMenu(titles, title="Välj kanal att ta bort:")
    idx = menu.show()
    
    if idx is not None and idx < len(outlines):
        body.remove(outlines[idx])
        tree.write(OPML_FILE, encoding='UTF-8', xml_declaration=True)
        print("Kanal borttagen.")

async def fetch_feed(session, url):
    try:
        async with session.get(url, headers={"User-Agent": USER_AGENT}) as response:
            if response.status == 200:
                return await response.text()
    except:
        return None

async def show_video_menu(videos):
    """Visar en meny med videor och hämtar metadata vid behov."""
    global SHOW_SHORTS

    # Filtrera om SHOW_SHORTS är False
    if not SHOW_SHORTS:
        videos = [v for v in videos if not v.get('is_shorts')]
        if not videos:
            print("Inga videor att visa (Shorts är dolda).")
            # Vänta lite så användaren hinner läsa, eller bara returnera
            await asyncio.sleep(1.5)
            return

    # Identifiera videor som saknar duration (vi kollar de 40 första synliga)
    to_fetch = [v for v in videos[:40] if v['duration'] == "??:??"]
    
    if to_fetch:
        print(f"Hämtar metadata för {len(to_fetch)} videor...")
        sem = asyncio.Semaphore(5)
        
        async def fetch_and_update(v):
            async with sem:
                dur = await get_video_duration(v['link'], v['id'])
                v['duration'] = dur
                if dur != "??:??":
                    try:
                        parts = dur.split(':')
                        # Om video är under 61 sekunder, markera som shorts
                        if len(parts) == 2:
                            m, s = int(parts[0]), int(parts[1])
                            if m == 0 or (m == 1 and s == 0):
                                v['is_shorts'] = True
                    except: pass

        await asyncio.gather(*(fetch_and_update(v) for v in to_fetch))
        
        # Omfiltrering ifall nya shorts upptäcktes efter metadatahämtning
        if not SHOW_SHORTS:
            videos = [v for v in videos if not v.get('is_shorts')]
            if not videos:
                print("Alla videor var Shorts och filtrerades bort.")
                await asyncio.sleep(1.5)
                return

    while True:
        menu_entries = []
        for v in videos:
            dt = datetime(*v['published'][:6]).strftime("%m-%d %H:%M")
            seen_mark = "✔" if v['is_seen'] else " "
            shorts_mark = "[SHORTS] " if v.get('is_shorts') else ""
            duration = v.get('duration', '??:??')
            
            # Sanera titeln
            safe_title = clean_title(v['title'])
            
            entry = f"[{seen_mark}] {dt}  {duration:<6}  {v['channel'][:12]:<12}  {shorts_mark}{safe_title}"
            menu_entries.append(entry)
        
        menu_entries.append("[Gå tillbaka]")
        
        title_suffix = "(Shorts dolda)" if not SHOW_SHORTS else ""
        menu = TerminalMenu(
            menu_entries, 
            title=f"Välj video {title_suffix} (Sök genom att skriva):"
        )
        idx = menu.show()
        
        if idx is None or idx == len(videos):
            break
            
        video = videos[idx]
        mark_as_seen(video['id'], video['title'])
        video['is_seen'] = True
        
        print(f"Startar QuickTube för: {video['title']}")
        try:
            subprocess.run(["wl-copy", video['link']])
            subprocess.run([QUICKTUBE_CMD])
        except Exception as e:
            print(f"Fel vid start: {e}")

async def main_async():
    global duration_cache, SHOW_SHORTS
    init_db()
    duration_cache = get_cached_metadata()
    
    while True:
        feeds = load_feeds_from_opml()
        seen_ids = get_seen_videos()
        
        if not feeds:
            print("\nInga kanaler hittades. [a] Lägg till.")
        
        all_videos_by_channel = {}
        all_videos_flat = []

        print("Hämtar flöden...")
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
                
                # Om vi vet längden från cache, uppdatera shorts-status direkt
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

        # Huvudmeny
        channel_names = sorted(all_videos_by_channel.keys())
        menu_options = []
        
        # Räkna ofiltrerade olästa
        unread_total = len([v for v in all_videos_flat if not v['is_seen']])
        
        # Anpassa texten för filtret
        filter_status = "DÖLJ" if SHOW_SHORTS else "VISA"
        
        menu_options.append(f"--- ALLA VIDEOR ({unread_total} nya) ---")
        
        for name in channel_names:
            unread_count = len([v for v in all_videos_by_channel[name] if not v['is_seen']])
            menu_options.append(f"{name} ({unread_count})")
            
        menu_options.extend([
            "-" * 30, 
            "[a] Lägg till kanal", 
            "[d] Ta bort kanal", 
            f"[s] {filter_status} Shorts",
            "[q] Avsluta"
        ])
        
        main_menu = TerminalMenu(menu_options, title=f"YT-RSS Discovery (Shorts: {'PÅ' if SHOW_SHORTS else 'AV'})")
        choice_idx = main_menu.show()
        
        if choice_idx is None: break
        choice_text = menu_options[choice_idx]
        
        if choice_text == "[q] Avsluta":
            sys.exit()
        elif choice_text == "[a] Lägg till kanal":
            url = await asyncio.to_thread(input, "Klistra in RSS-URL: ")
            url = url.strip()
            if url: add_feed_to_opml(url)
        elif choice_text == "[d] Ta bort kanal":
            remove_channel_ui()
        elif "[s]" in choice_text:
            SHOW_SHORTS = not SHOW_SHORTS
            # Vi loopar om så listan ritas om direkt med nytt filterstatus
            continue
        elif "--- ALLA VIDEOR" in choice_text:
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
