# ytrss 📺

Ett snabbt och lättviktigt TUI-verktyg för att bläddra och titta på YouTube-prenumerationer via RSS, direkt i terminalen. Byggt för Linux med Unix-filosofin i åtanke.

Designad för att fungera sömlöst med [QuickTube](https://github.com/coffe/QuickTube) (eller andra videospelare).

## ✨ Funktioner

*   **Blixtsnabb:** Hämtar alla RSS-flöden asynkront (samtidigt) vid start.
*   **Ren TUI:** Navigera enkelt med piltangenterna och sök/filtrera genom att skriva direkt i menyn.
*   **Shorts-hantering:** Identifierar automatiskt Shorts (< 60s) och låter dig dölja dem med ett knapptryck.
*   **Smart:** Sparar sedda videor och cachar videolängder i en lokal SQLite-databas.
*   **OPML-stöd:** Importera/Exportera dina prenumerationer enkelt.
*   **Portabel:** Byggs till en enda binärfil utan beroenden.

## 🚀 Installation

### Alternativ 1: Bygg från källkod (Rekommenderas)
Du behöver bara ha Python 3 installerat.

```bash
git clone https://github.com/coffe/ytrss.git
cd ytrss
./build.sh
```

Detta skapar en körbar fil i `dist/ytrss`. Kopiera den till din `$PATH`:

```bash
cp dist/ytrss ~/bin/  # eller /usr/local/bin/
```

## 🎮 Användning

Starta programmet:

```bash
ytrss
```

### Kortkommandon i menyn
*   **`Upp/Ner`**: Navigera i listan.
*   **`Enter`**: Välj kanal eller spela upp video.
*   **`Skriv text`**: Filtrerar listan direkt (t.ex. skriv "linux" för att bara se Linux-relaterade kanaler/videor).
*   **`s`**: Visa/Dölj Shorts (toggle).
*   **`a`**: Lägg till ny RSS-länk.
*   **`d`**: Ta bort en kanal.
*   **`q`**: Avsluta.

## ⚙️ Konfiguration
All data sparas i `~/.config/ytrss/`:
*   `ytRss.opml`: Dina prenumerationer.
*   `ytrss.db`: Databas med historik och metadata.

## 🔧 Krav
*   Python 3.8+
*   `yt-dlp` (för att hämta videolängder/metadata).
*   `wl-copy` (Wayland) eller `xclip` (X11) för urklippshantering.
*   `quicktube` (rekommenderas för uppspelning, men kan anpassas).

## 📄 Licens
MIT

---

**⚠️ Ansvarsfriskrivning:** Detta projekt är skapat enbart i utbildningssyfte. Det är inte avsett att användas för att ladda ner upphovsrättsskyddat material utan tillåtelse eller för att bryta mot YouTubes användarvillkor. Använd verktyget ansvarsfullt.
