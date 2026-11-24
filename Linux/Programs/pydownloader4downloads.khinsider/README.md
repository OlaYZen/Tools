# KHInsider Album Downloader

> [!NOTE]
> **NO ACCOUNT NEEDED:**
> This script allows you to download entire albums **without** requiring a khinsider account, unlike the website which requires registration for bulk downloads.

A high-performance, multithreaded Python script for downloading complete music albums from [downloads.khinsider.com](https://downloads.khinsider.com/). Perfect for downloading video game soundtracks and other music collections without requiring a khinsider account.

## Features

- 🎵 **Smart Quality Selection**: Automatically downloads the highest quality audio format available (FLAC → MP3 → M4A)
- 🚫 **No Account Required**: Download entire albums without needing a khinsider account
- ⚡ **Multithreaded Downloads**: Configurable concurrent downloads for maximum speed
- 📁 **Organized Storage**: Creates clean folder structures with sanitized album names
- 🔄 **Retry Logic**: Automatic retry mechanism for failed downloads
- ⚙️ **Configurable Settings**: Customizable download paths, thread counts, and format priorities
- 📊 **Progress Tracking**: Real-time download progress with visual indicators

## Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/OlaYZen/pydownloader4downloads.khinsider.git
   cd pydownloader4downloads.khinsider
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

## Usage

1. **Run the script**
   ```bash
   python Downloader.py
   ```

2. **Enter the album URL** when prompted
   ```
   Enter the URL: https://downloads.khinsider.com/game-soundtrack/album-name
   ```

3. **Wait for download completion**
   - Files will be organized in folders by album name
   - Progress bars will show download status
   - Failed downloads will be reported at the end

## Configuration

Customize the script behavior by editing `settings.ini`:

### Download Settings
```ini
[Download]
priority_order = flac, mp3, m4a    # Audio format preference
download_path =                    # Custom download directory (optional)
```

### Performance Settings
```ini
[Threads]
max_workers = 1                    # Number of concurrent downloads (0 = use all CPU cores)

[Retries]
max_retries = 2                    # Retry attempts for failed downloads
```

### Example Custom Paths
- **Windows**: `C:\Music\Downloads`
- **Linux/Mac**: `/home/user/Music/Downloads`
- **Leave empty** to use default `Audio files/` folder

## System Requirements

- **Python**: 3.7 or higher
- **RAM**: 8GB recommended (4GB minimum)
- **Storage**: Sufficient space for audio files
- **Internet**: Stable connection for downloads

## File Organization

Downloads are organized as follows:
```
Audio files/
└── Album Name (Platform) (Type) (Year)/
    ├── 01. Track Name.flac
    ├── 02. Track Name.flac
    └── ...
```

## Troubleshooting

- **Script crashes**: Reduce `max_workers` in settings.ini or ensure sufficient RAM
- **Failed downloads**: Check internet connection; failed URLs will be listed at completion
- **Slow performance**: Increase `max_workers` (but not beyond your CPU core count)
- **Permission errors**: Ensure write permissions for the download directory

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.