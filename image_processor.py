import mysql.connector
import json
import shutil
import os
import re
import subprocess
import logging
from pathlib import Path
from configparser import ConfigParser
from PIL import Image
from datetime import datetime, timedelta

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(filename)s:%(funcName)s:%(lineno)d - %(message)s',
    handlers=[
        logging.FileHandler('media_processor.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

def get_db_connection():
    config = ConfigParser()
    config.read('credentials.ini')

    return mysql.connector.connect(
        host=config.get('database', 'db_host'),
        database=config.get('database', 'db_name'),
        user=config.get('database', 'db_user'),
        password=config.get('database', 'db_password'),
        port=config.getint('database', 'db_port')
    )

def get_camera_data():
    logger.info("Fetching camera data from database")
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT c.device_id, c.serial_id, c.site_id, s.name as site_name, c.timezone, ss.last_added_time
        FROM camera.camera c
        LEFT JOIN camera.site s ON c.site_id = s.site_id
        LEFT JOIN (SELECT device_id, MAX(time) last_added_time FROM camera.snapshot GROUP BY device_id) ss
            ON ss.device_id = c.device_id
    """)

    results = cursor.fetchall()
    cursor.close()
    conn.close()

    logger.info(f"Fetched {len(results)} camera records")
    return results

def get_camera_dict():
    """Returns a dictionary with serial_id as key"""
    cameras = get_camera_data()
    return {cam['serial_id']: cam for cam in cameras}

def get_valid_serial_ids():
    """Returns a set of all valid serial_ids from the database"""
    cameras = get_camera_data()
    return {cam['serial_id'] for cam in cameras}

def parse_folder_name(folder_name):
    """Extract serial_id from folder name format: <serial_id>_<WTP or WOTP>"""
    parts = folder_name.split('_')
    if len(parts) >= 2 and parts[-1] in ['WTP', 'WOTP']:
        return '_'.join(parts[:-1])
    return None

def clean_subfolder_name(name, serial_id):
    """
    Clean subfolder name:
    1. Remove serial_id prefix and following underscore if present
    2. Replace spaces with underscores
    3. Remove special characters including brackets
    """
    # Remove serial_id prefix if present (case insensitive)
    if serial_id and name.lower().startswith(serial_id.lower()):
        name = name[len(serial_id):]
        # Remove leading underscore if present
        if name.startswith('_'):
            name = name[1:]

    # Replace spaces with underscores
    name = name.replace(' ', '_')

    # Remove brackets and other special characters, keep alphanumeric, underscore, hyphen
    name = re.sub(r'[^\w\-]', '', name)

    return name

def get_disk_usage(path):
    """Get disk usage percentage for given path"""
    stat = os.statvfs(path)
    total = stat.f_blocks * stat.f_frsize
    free = stat.f_bavail * stat.f_frsize
    used = total - free
    usage_percent = (used / total) * 100
    return usage_percent

def select_destination_disk():
    """Select disk1 or disk3 based on usage, prioritize disk1"""
    disk1_usage = get_disk_usage('/mnt/disk1')

    if disk1_usage < 85:
        logger.info(f"Using disk1 (usage: {disk1_usage:.1f}%)")
        return Path('/mnt/disk1/media')

    disk3_usage = get_disk_usage('/mnt/disk3')

    if disk3_usage < 85:
        logger.info(f"disk1 is over 85% ({disk1_usage:.1f}%), using disk3 (usage: {disk3_usage:.1f}%)")
        return Path('/mnt/disk3/media')

    # Both disks over 85%, still use disk1 but warn
    logger.warning(f"Both disks over 85% (disk1: {disk1_usage:.1f}%, disk3: {disk3_usage:.1f}%) - using disk1 anyway")
    return Path('/mnt/disk1/media')

def is_millisecond_format(filename):
    """Check if filename is already in millisecond timestamp format"""
    name_without_ext = Path(filename).stem
    # Check if it's a 13-digit number (milliseconds) optionally followed by _counter
    pattern = r'^\d{13}(_\d+)?$'
    return bool(re.match(pattern, name_without_ext))

def get_timestamp_from_filename(filename):
    """Extract timestamp from millisecond format filename"""
    name_without_ext = Path(filename).stem
    # Extract the 13-digit number
    match = re.match(r'^(\d{13})(_\d+)?$', name_without_ext)
    if match:
        return int(match.group(1))
    return None

def get_image_timestamp(image_path):
    """Get timestamp in milliseconds from image using exiftool"""
    try:
        result = subprocess.run(
            ['exiftool', '-DateTimeOriginal', '-s3', str(image_path)],
            capture_output=True,
            text=True,
            timeout=10
        )

        if result.returncode == 0 and result.stdout.strip():
            # Parse datetime string: "2024:10:23 14:30:45"
            datetime_str = result.stdout.strip()
            from datetime import datetime
            dt = datetime.strptime(datetime_str, '%Y:%m:%d %H:%M:%S')
            timestamp_ms = int(dt.timestamp() * 1000)
            return timestamp_ms
    except Exception as e:
        logger.warning(f"Could not get timestamp for {image_path.name}: {e}")

    return None

def create_thumbnail(image_path, thumbnail_dir):
    """Create a thumbnail (150x84) for the given image"""
    try:
        # Create thumbnail directory if it doesn't exist
        thumbnail_dir.mkdir(parents=True, exist_ok=True)

        # Check if thumbnail already exists
        thumbnail_path = thumbnail_dir / image_path.name
        if thumbnail_path.exists():
            return True

        # Open image
        with Image.open(image_path) as img:
            # Create thumbnail with size (150, 84)
            img.thumbnail((150, 84), Image.Resampling.LANCZOS)

            # Save thumbnail with same filename
            img.save(thumbnail_path, quality=85, optimize=True)

            return True
    except Exception as e:
        logger.warning(f"Could not create thumbnail for {image_path.name}: {e}")
        return False

def create_thumbnails_for_folder(folder_path):
    """Create thumbnails for all images in the folder structure"""
    folder_path = Path(folder_path)
    image_extensions = {'.jpg', '.jpeg', '.png', '.tiff', '.tif', '.bmp'}

    logger.info(f"Checking/creating thumbnails for {folder_path.name}")

    # Find all image files
    all_images = [f for f in folder_path.rglob('*')
                  if f.is_file() and f.suffix.lower() in image_extensions
                  and 'thumbnail' not in f.parts]

    if not all_images:
        logger.info("No images found in folder")
        return 0

    thumbnail_count = 0
    created_count = 0

    for img_path in all_images:
        # Create thumbnail directory in the same subfolder
        thumbnail_dir = img_path.parent / 'thumbnail'
        thumbnail_path = thumbnail_dir / img_path.name

        if not thumbnail_path.exists():
            if create_thumbnail(img_path, thumbnail_dir):
                created_count += 1
                thumbnail_count += 1
        else:
            thumbnail_count += 1

    logger.info(f"Thumbnails: {thumbnail_count} total ({created_count} newly created)")
    return created_count

def preprocess_folder(folder_path, serial_id):
    """Clean folder names, rename subfolders, and rename images with timestamps"""
    folder_path = Path(folder_path)
    logger.info(f"Preprocessing folder: {folder_path.name}")

    # Step 1: Rename all subfolders (bottom-up to avoid path issues)
    all_dirs = sorted([d for d in folder_path.rglob('*') if d.is_dir()],
                      key=lambda x: len(str(x)), reverse=True)

    renamed_folders = 0
    for subdir in all_dirs:
        # Skip thumbnail directories
        if subdir.name == 'thumbnail':
            continue

        cleaned_name = clean_subfolder_name(subdir.name, serial_id)
        if cleaned_name != subdir.name and cleaned_name:  # Ensure not empty
            new_path = subdir.parent / cleaned_name
            logger.debug(f"Renaming folder: '{subdir.name}' -> '{cleaned_name}'")
            subdir.rename(new_path)
            renamed_folders += 1

    if renamed_folders > 0:
        logger.info(f"Renamed {renamed_folders} subfolders")

    # Step 2: Rename all images based on timestamp
    image_extensions = {'.jpg', '.jpeg', '.png', '.tiff', '.tif', '.bmp'}
    all_images = [f for f in folder_path.rglob('*')
                  if f.is_file() and f.suffix.lower() in image_extensions
                  and 'thumbnail' not in f.parts]

    renamed_images = 0
    skipped_images = 0

    for img_path in all_images:
        # Skip if already in millisecond format
        if is_millisecond_format(img_path.name):
            skipped_images += 1
            continue

        timestamp = get_image_timestamp(img_path)

        if timestamp:
            new_name = f"{timestamp}{img_path.suffix}"
            new_path = img_path.parent / new_name

            # Handle duplicate timestamps
            counter = 1
            while new_path.exists():
                new_name = f"{timestamp}_{counter}{img_path.suffix}"
                new_path = img_path.parent / new_name
                counter += 1

            logger.debug(f"Renaming image: {img_path.name} -> {new_name}")
            img_path.rename(new_path)
            renamed_images += 1
        else:
            logger.warning(f"Keeping original name: {img_path.name} (no timestamp found)")

    logger.info(f"Renamed {renamed_images} images, skipped {skipped_images} already processed")

def verify_copy(source, destination):
    """Verify the copy was successful by comparing file counts and total size"""
    src_files = list(Path(source).rglob('*'))
    dst_files = list(Path(destination).rglob('*'))

    src_count = len([f for f in src_files if f.is_file()])
    dst_count = len([f for f in dst_files if f.is_file()])

    return src_count == dst_count and src_count > 0

def get_folder_age(folder_path):
    """Get the age of the folder in hours"""
    try:
        stat_info = folder_path.stat()
        # Use the most recent of mtime or ctime
        mod_time = max(stat_info.st_mtime, stat_info.st_ctime)
        age_hours = (datetime.now().timestamp() - mod_time) / 3600
        return age_hours
    except:
        return float('inf')

def get_todays_folders():
    """Get folders from both disk1 and disk3 that were created/modified within last 24 hours"""
    logger.info("Scanning for folders modified in last 24 hours")
    todays_folders = []

    for disk in ['/mnt/disk1/media', '/mnt/disk3/media']:
        disk_path = Path(disk)
        if not disk_path.exists():
            logger.warning(f"Path does not exist: {disk}")
            continue

        logger.info(f"Scanning {disk}...")
        folder_count = 0

        for folder in disk_path.iterdir():
            if folder.is_dir():
                folder_count += 1
                age_hours = get_folder_age(folder)

                # Consider folders less than 24 hours old
                if age_hours < 24:
                    todays_folders.append(folder)
                    logger.debug(f"Found: {folder.name} (age: {age_hours:.1f} hours)")

        logger.info(f"Total folders in {disk}: {folder_count}")

    logger.info(f"Found {len(todays_folders)} folders from last 24 hours")
    return todays_folders

def has_thumbnail(image_path):
    """Check if thumbnail exists for the given image"""
    thumbnail_path = image_path.parent / 'thumbnail' / image_path.name
    return thumbnail_path.exists()

def insert_snapshots_to_db(folder_path, camera_info):
    """Insert snapshots from folder to database"""
    folder_path = Path(folder_path)
    image_extensions = {'.jpg', '.jpeg', '.png', '.tiff', '.tif', '.bmp'}

    logger.info(f"Checking snapshots for device_id: {camera_info['device_id']}")

    # Get all images (excluding thumbnails)
    all_images = [f for f in folder_path.rglob('*')
                  if f.is_file() and f.suffix.lower() in image_extensions
                  and 'thumbnail' not in f.parts]

    if not all_images:
        logger.info("No images to insert")
        return 0

    # Get last_added_time for this device
    last_added_time = camera_info.get('last_added_time')
    if last_added_time:
        # Convert to milliseconds if it's a datetime object
        if isinstance(last_added_time, datetime):
            last_added_time = int(last_added_time.timestamp() * 1000)
        else:
            last_added_time = int(last_added_time)
    else:
        last_added_time = 0

    # Get max timestamp from folder
    max_timestamp = 0
    for img in all_images:
        timestamp = get_timestamp_from_filename(img.name)
        if timestamp:
            max_timestamp = max(max_timestamp, timestamp)

    logger.info(f"Last added time in DB: {last_added_time}, Max timestamp in folder: {max_timestamp}")

    # If last_added_time matches max_timestamp, skip
    if last_added_time >= max_timestamp:
        logger.info("Skipping - DB is up to date")
        return 0

    # Prepare data for insertion
    snapshots_to_insert = []

    for img_path in all_images:
        timestamp = get_timestamp_from_filename(img_path.name)

        if not timestamp:
            logger.warning(f"Could not extract timestamp from {img_path.name}")
            continue

        # Skip if already in database
        if timestamp <= last_added_time:
            continue

        # Get area_name (subfolder name)
        relative_path = img_path.relative_to(folder_path)
        area_name = relative_path.parts[0] if len(relative_path.parts) > 1 else "unknown"

        # Construct URL
        url = str(img_path)

        # Check if thumbnail exists (1 or 0)
        thumbnail_flag = 1 if has_thumbnail(img_path) else 0

        snapshot = {
            'device_id': camera_info['device_id'],
            'time': timestamp,
            'url': url,
            'thumbnail': thumbnail_flag,
            'timezone': camera_info.get('timezone', 'UTC'),
            'area_name': area_name,
            'created_by': 0,  # System
            'updated_by': 0,  # System
            'preset_id': 0,
            'adjusted_start_time': 0
        }

        snapshots_to_insert.append(snapshot)

    if not snapshots_to_insert:
        logger.info("No new snapshots to insert")
        return 0

    # Insert into database
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        insert_query = """
            INSERT INTO camera.snapshot
            (device_id, time, url, thumbnail, timezone, area_name, created_by, updated_by, preset_id, adjusted_start_time)
            VALUES (%(device_id)s, %(time)s, %(url)s, %(thumbnail)s, %(timezone)s, %(area_name)s,
                    %(created_by)s, %(updated_by)s, %(preset_id)s, %(adjusted_start_time)s)
        """

        cursor.executemany(insert_query, snapshots_to_insert)
        conn.commit()

        inserted_count = cursor.rowcount
        cursor.close()
        conn.close()

        logger.info(f"Inserted {inserted_count} snapshots for device_id: {camera_info['device_id']}")
        return inserted_count

    except Exception as e:
        logger.error(f"Error inserting snapshots: {e}", exc_info=True)
        return 0

def start_rsync():
    """Start rsync to mirror disk1 to disk2 and disk3 to disk4"""
    logger.info("Starting rsync backup processes")

    rsync_jobs = [
        {
            'source': '/mnt/disk1/',
            'dest': '/mnt/disk2/',
            'name': 'disk1 → disk2'
        },
        {
            'source': '/mnt/disk3/',
            'dest': '/mnt/disk4/',
            'name': 'disk3 → disk4'
        }
    ]

    for job in rsync_jobs:
        logger.info(f"Starting rsync: {job['name']}")
        try:
            cmd = [
                'nohup',
                'rsync',
                '-av',
                '--delete',
                '--progress',
                job['source'],
                job['dest']
            ]

            subprocess.Popen(
                cmd,
                stdout=open(f'/tmp/rsync_{job["name"].replace(" → ", "_to_")}.log', 'w'),
                stderr=subprocess.STDOUT,
                start_new_session=True
            )

            logger.info(f"Rsync started for {job['name']} - Log: /tmp/rsync_{job['name'].replace(' → ', '_to_')}.log")

        except Exception as e:
            logger.error(f"Error starting rsync for {job['name']}: {e}", exc_info=True)

def update_preset_numbers():
    """Update preset numbers based on alphabetically ordered area_name for each device"""
    logger.info("Updating preset numbers based on area_name ordering")
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        update_query = """
            UPDATE snapshot s
            JOIN (
                SELECT 
                    ROW_NUMBER() OVER (PARTITION BY device_id ORDER BY area_name) AS order_number,
                    area_name,
                    device_id
                FROM snapshot
                WHERE area_name IS NOT NULL
                GROUP BY device_id, area_name
            ) AS area_order ON s.area_name = area_order.area_name 
                            AND s.device_id = area_order.device_id
            SET s.preset_id = area_order.order_number
            WHERE s.area_name IS NOT NULL
        """
        
        cursor.execute(update_query)
        conn.commit()
        
        updated_count = cursor.rowcount
        cursor.close()
        conn.close()
        
        logger.info(f"Updated preset numbers for {updated_count} snapshot records")
        return updated_count
        
    except Exception as e:
        logger.error(f"Error updating preset numbers: {e}", exc_info=True)
        return 0

def process_ftp_folders():
    logger.info("=" * 60)
    logger.info("Starting media processor")
    logger.info("=" * 60)

    source_base = Path('/mnt/disk5/ftpdata/media')

    camera_dict = get_camera_dict()
    valid_serial_ids = set(camera_dict.keys())

    processed_count = 0

    # Process folders from FTP location
    if source_base.exists():
        logger.info(f"Checking FTP location: {source_base}")
        ftp_folders = [f for f in source_base.iterdir() if f.is_dir()]
        logger.info(f"Found {len(ftp_folders)} folders in FTP location")

        for folder in ftp_folders:
            folder_name = folder.name
            serial_id = parse_folder_name(folder_name)

            if not serial_id:
                logger.warning(f"Skipping '{folder_name}' - invalid format")
                continue

            if serial_id not in valid_serial_ids:
                logger.warning(f"Skipping '{folder_name}' - serial_id '{serial_id}' not in database")
                continue

            logger.info(f"Processing '{folder_name}' from FTP")

            # Preprocess: clean names and rename images
            try:
                preprocess_folder(folder, serial_id)
            except Exception as e:
                logger.error(f"Error during preprocessing '{folder_name}': {e}", exc_info=True)
                continue

            # Create thumbnails before copying
            try:
                create_thumbnails_for_folder(folder)
            except Exception as e:
                logger.error(f"Error creating thumbnails for '{folder_name}': {e}", exc_info=True)
                continue

            # Select destination disk based on usage
            dest_base = select_destination_disk()
            dest_path = dest_base / folder_name

            logger.info(f"Copying to {dest_path}")

            try:
                shutil.copytree(folder, dest_path, dirs_exist_ok=True)

                # Verify copy
                if verify_copy(folder, dest_path):
                    logger.info(f"Copy verified. Deleting source folder: {folder}")
                    shutil.rmtree(folder)
                    logger.info(f"Successfully processed '{folder_name}'")
                    processed_count += 1
                else:
                    logger.error(f"Copy verification failed for '{folder_name}' - source NOT deleted")

            except Exception as e:
                logger.error(f"Error copying '{folder_name}': {e}", exc_info=True)
    else:
        logger.warning(f"FTP location does not exist: {source_base}")

    # Process today's folders that might need post-processing
    logger.info("=" * 60)
    logger.info("Post-processing phase")
    logger.info("=" * 60)

    todays_folders = get_todays_folders()

    total_snapshots_inserted = 0

    for folder in todays_folders:
        folder_name = folder.name
        serial_id = parse_folder_name(folder_name)

        if not serial_id:
            logger.warning(f"Skipping '{folder_name}' - invalid format")
            continue

        if serial_id not in camera_dict:
            logger.warning(f"Skipping '{folder_name}' - serial_id not in database")
            continue

        logger.info(f"Post-processing '{folder_name}'")

        # Check if thumbnails need to be created
        try:
            created = create_thumbnails_for_folder(folder)
            if created > 0:
                processed_count += 1
        except Exception as e:
            logger.error(f"Error processing thumbnails for '{folder_name}': {e}", exc_info=True)

        # Insert snapshots to database
        try:
            camera_info = camera_dict[serial_id]
            inserted = insert_snapshots_to_db(folder, camera_info)
            total_snapshots_inserted += inserted
            if inserted > 0:
                processed_count += 1
        except Exception as e:
            logger.error(f"Error inserting snapshots for '{folder_name}': {e}", exc_info=True)

    # Update preset numbers after all snapshots are inserted
    logger.info("=" * 60)
    logger.info("Updating preset numbers")
    logger.info("=" * 60)

    try:
        update_preset_numbers()
    except Exception as e:
        logger.error(f"Error updating preset numbers: {e}", exc_info=True)

    # Start rsync after processing all folders
    logger.info("=" * 60)
    logger.info("Summary")
    logger.info("=" * 60)

    if processed_count > 0:
        logger.info(f"Processed {processed_count} folder(s)")
        logger.info(f"Inserted {total_snapshots_inserted} total snapshots to database")
        start_rsync()
    else:
        logger.info("No folders were processed. Skipping rsync.")


# Usage
if __name__ == "__main__":
    try:
        process_ftp_folders()
    except Exception as e:
        logger.error(f"Fatal error in main process: {e}", exc_info=True)
        raise
