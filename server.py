import os
import logging
import hashlib
from pathlib import Path
from urllib.parse import unquote
from flask import Flask, send_file, jsonify, request
from werkzeug.exceptions import NotFound, BadRequest
import base64
from datetime import datetime, timezone, timedelta
from configparser import ConfigParser
import mysql.connector
from PIL import Image
from io import BytesIO

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(filename)s:%(funcName)s:%(lineno)d - %(message)s',
    handlers=[
        logging.FileHandler('image_server.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Security keyword for token generation
TOKEN_KEYWORD = "hardwork"

# Token validity duration in minutes
TOKEN_VALIDITY_MINUTES = 30

# Allowed base paths for security
ALLOWED_BASE_PATHS = [
    '/mnt/disk1/media',
    '/mnt/disk2/media',
    '/mnt/disk3/media',
    '/mnt/disk4/media'
]

# Allowed image extensions
ALLOWED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.tif', '.webp'}

def get_db_connection():
    """Get database connection"""
    config = ConfigParser()
    config.read('credentials.ini')

    return mysql.connector.connect(
        host=config.get('database', 'db_host'),
        database=config.get('database', 'db_name'),
        user=config.get('database', 'db_user'),
        password=config.get('database', 'db_password'),
        port=config.getint('database', 'db_port')
    )

def get_device_by_id(device_id):
    """Get device information from database"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("""
            SELECT device_id, serial_id, site_id, timezone
            FROM camera.camera
            WHERE device_id = %s
        """, (device_id,))

        result = cursor.fetchone()
        cursor.close()
        conn.close()

        return result
    except Exception as e:
        logger.error(f"Error fetching device {device_id}: {e}")
        return None

def get_current_time_window():
    """
    Get current 30-minute time window
    Returns timestamp rounded down to nearest 30 minutes
    """
    now = datetime.now(timezone.utc)
    # Round down to nearest 30 minutes
    minutes = (now.minute // TOKEN_VALIDITY_MINUTES) * TOKEN_VALIDITY_MINUTES
    time_window = now.replace(minute=minutes, second=0, microsecond=0)
    return time_window

def create_token(device_id, keyword=TOKEN_KEYWORD):
    """
    Create token for device_id validation with 30-minute expiration
    Format: SHA256(device_id-keyword-YYYY-MM-DD-HH-MM)
    Where MM is rounded to nearest 30-minute interval (00 or 30)
    """
    time_window = get_current_time_window()

    # Format: YYYY-MM-DD-HH-MM (e.g., "2025-10-24-14-30")
    time_str = time_window.strftime("%Y-%m-%d-%H-%M")

    # Concatenate the device_id, keyword, and time window
    raw_string = f"{device_id}-{keyword}-{time_str}"

    # Generate a hash of the concatenated string
    token = hashlib.sha256(raw_string.encode()).hexdigest()

    logger.debug(f"Generated token for device {device_id} at time window {time_str}: {token}")
    return token, time_window

def validate_token(device_id, provided_token):
    """
    Validate the provided token against the calculated token
    Checks current 30-minute window and previous window (grace period)
    """
    # Check current time window
    current_token, current_window = create_token(device_id)
    if provided_token == current_token:
        logger.info(f"Token validated for device {device_id} (current window)")
        return True

    # Check previous time window (grace period for requests near boundary)
    previous_window = get_current_time_window() - timedelta(minutes=TOKEN_VALIDITY_MINUTES)
    previous_time_str = previous_window.strftime("%Y-%m-%d-%H-%M")
    raw_string = f"{device_id}-{TOKEN_KEYWORD}-{previous_time_str}"
    previous_token = hashlib.sha256(raw_string.encode()).hexdigest()

    if provided_token == previous_token:
        logger.info(f"Token validated for device {device_id} (previous window - grace period)")
        return True

    logger.warning(f"Token validation failed for device {device_id}")
    return False

def is_safe_path(file_path):
    """Check if the requested path is within allowed directories"""
    try:
        # Resolve to absolute path
        abs_path = Path(file_path).resolve()

        # Check if path is within any allowed base path
        for base_path in ALLOWED_BASE_PATHS:
            if str(abs_path).startswith(str(Path(base_path).resolve())):
                return True

        return False
    except Exception as e:
        logger.error(f"Error checking path safety: {e}")
        return False

def is_allowed_extension(file_path):
    """Check if file has an allowed image extension"""
    return Path(file_path).suffix.lower() in ALLOWED_EXTENSIONS

def parse_size_parameter(size_str):
    """
    Parse size parameter in format 'WIDTHxHEIGHT' (e.g., '640x480')
    Returns tuple (width, height) or None if invalid
    """
    try:
        if not size_str or 'x' not in size_str.lower():
            return None
        
        parts = size_str.lower().split('x')
        if len(parts) != 2:
            return None
        
        width = int(parts[0])
        height = int(parts[1])
        
        # Validate reasonable dimensions (1-10000 pixels)
        if width < 1 or width > 10000 or height < 1 or height > 10000:
            return None
        
        return (width, height)
    except (ValueError, AttributeError):
        return None

def resize_image(image_path, target_size):
    """
    Resize image to target size
    Returns BytesIO object containing resized image
    """
    try:
        # Open image
        with Image.open(image_path) as img:
            # Convert to RGB if necessary (for transparency)
            if img.mode in ('RGBA', 'LA', 'P'):
                # Create white background
                background = Image.new('RGB', img.size, (255, 255, 255))
                if img.mode == 'P':
                    img = img.convert('RGBA')
                background.paste(img, mask=img.split()[-1] if img.mode in ('RGBA', 'LA') else None)
                img = background
            elif img.mode != 'RGB':
                img = img.convert('RGB')
            
            # Resize image maintaining aspect ratio
            img.thumbnail(target_size, Image.Resampling.LANCZOS)
            
            # Save to BytesIO
            img_io = BytesIO()
            
            # Determine format based on original extension
            ext = Path(image_path).suffix.lower()
            if ext in ['.jpg', '.jpeg']:
                img.save(img_io, 'JPEG', quality=85, optimize=True)
                mimetype = 'image/jpeg'
            elif ext == '.png':
                img.save(img_io, 'PNG', optimize=True)
                mimetype = 'image/png'
            elif ext == '.webp':
                img.save(img_io, 'WEBP', quality=85)
                mimetype = 'image/webp'
            else:
                # Default to JPEG for other formats
                img.save(img_io, 'JPEG', quality=85, optimize=True)
                mimetype = 'image/jpeg'
            
            img_io.seek(0)
            return img_io, mimetype
            
    except Exception as e:
        logger.error(f"Error resizing image {image_path}: {e}")
        raise

@app.route('/image', methods=['GET'])
def get_image():
    """
    Serve image from disk with authentication and optional resizing

    Query parameters:
    - path: URL-encoded or base64-encoded file path
    - device_id: Device ID (required)
    - token: Authentication token (required)
    - encoding: 'base64' or 'url' (default: 'url')
    - size: Optional size in format 'WIDTHxHEIGHT' (e.g., '640x480')

    Examples:
    - /image?path=/mnt/disk1/media/LAWA_01_WTP/Area_1/1729701045123.jpg&device_id=122&token=abc123...
    - /image?path=1/media/LAWA_01_WTP/Area_1/1729701045123.jpg&device_id=122&token=abc123...&size=640x480
    - /image?path=L21udC9kaXNrMS9tZWRpYS8uLi4=&device_id=122&token=abc123...&encoding=base64
    """
    try:
        # Get parameters
        encoded_path = request.args.get('path')
        device_id = request.args.get('device_id')
        provided_token = request.args.get('token')
        encoding = request.args.get('encoding', 'url')
        size_param = request.args.get('size')

        # Validate required parameters
        if not encoded_path:
            logger.warning("Missing 'path' parameter")
            return jsonify({'error': 'Missing path parameter'}), 400

        if not device_id:
            logger.warning("Missing 'device_id' parameter")
            return jsonify({'error': 'Missing device_id parameter'}), 401

        if not provided_token:
            logger.warning("Missing 'token' parameter")
            return jsonify({'error': 'Missing token parameter'}), 401

        # Convert device_id to integer
        try:
            device_id = int(device_id)
        except ValueError:
            logger.warning(f"Invalid device_id: {device_id}")
            return jsonify({'error': 'Invalid device_id'}), 400

        # Validate token
        if not validate_token(device_id, provided_token):
            logger.warning(f"Invalid or expired token for device {device_id}")
            return jsonify({'error': 'Invalid or expired token'}), 403

        # Verify device exists in database
        device = get_device_by_id(device_id)
        if not device:
            logger.warning(f"Device not found: {device_id}")
            return jsonify({'error': 'Device not found'}), 404

        logger.info(f"Authenticated request from device {device_id} (serial: {device['serial_id']})")

        # Decode path based on encoding type
        if encoding == 'base64':
            try:
                file_path = base64.b64decode(encoded_path).decode('utf-8')
                logger.info(f"Decoded base64 path: {file_path}")
            except Exception as e:
                logger.error(f"Failed to decode base64 path: {e}")
                return jsonify({'error': 'Invalid base64 encoding'}), 400
        else:
            # URL decode
            file_path = unquote(encoded_path)
            logger.info(f"Decoded URL path: {file_path}")

        # Handle shortened path format: if path starts with a digit, prepend '/mnt/disk'
        if file_path and file_path[0].isdigit():
            file_path = f"/mnt/disk{file_path}"
            logger.info(f"Converted shortened path to: {file_path}")

        # Security checks
        if not is_safe_path(file_path):
            logger.warning(f"Unsafe path requested: {file_path}")
            return jsonify({'error': 'Access denied'}), 403

        if not is_allowed_extension(file_path):
            logger.warning(f"Invalid file extension requested: {file_path}")
            return jsonify({'error': 'Invalid file type'}), 400

        # Check if file exists, with fallback disk logic
        if not os.path.isfile(file_path):
            # If file doesn't exist on disk1, try disk2
            if '/mnt/disk1/' in file_path:
                fallback_path = file_path.replace('/mnt/disk1/', '/mnt/disk2/')
                if os.path.isfile(fallback_path):
                    logger.info(f"File not found on disk1, using disk2: {fallback_path}")
                    file_path = fallback_path
                else:
                    logger.warning(f"File not found: {file_path} (also checked disk2)")
                    return jsonify({'error': 'File not found'}), 404
            # If file doesn't exist on disk3, try disk4
            elif '/mnt/disk3/' in file_path:
                fallback_path = file_path.replace('/mnt/disk3/', '/mnt/disk4/')
                if os.path.isfile(fallback_path):
                    logger.info(f"File not found on disk3, using disk4: {fallback_path}")
                    file_path = fallback_path
                else:
                    logger.warning(f"File not found: {file_path} (also checked disk4)")
                    return jsonify({'error': 'File not found'}), 404
            else:
                logger.warning(f"File not found: {file_path}")
                return jsonify({'error': 'File not found'}), 404

        # Get file size for logging
        file_size = os.path.getsize(file_path)

        # Parse size parameter if provided
        target_size = parse_size_parameter(size_param)
        
        if target_size:
            # Resize the image
            logger.info(f"Resizing image to {target_size[0]}x{target_size[1]} for device {device_id}: {file_path}")
            try:
                img_io, mimetype = resize_image(file_path, target_size)
                resized_size = img_io.getbuffer().nbytes
                logger.info(f"Serving resized image to device {device_id}: {file_path} (original: {file_size:,} bytes, resized: {resized_size:,} bytes)")
                
                return send_file(
                    img_io,
                    mimetype=mimetype,
                    as_attachment=False,
                    download_name=Path(file_path).name
                )
            except Exception as e:
                logger.error(f"Error resizing image: {e}")
                return jsonify({'error': 'Failed to resize image'}), 500
        else:
            # Return original image
            # Determine mimetype
            ext = Path(file_path).suffix.lower()
            mimetype_map = {
                '.jpg': 'image/jpeg',
                '.jpeg': 'image/jpeg',
                '.png': 'image/png',
                '.gif': 'image/gif',
                '.bmp': 'image/bmp',
                '.tiff': 'image/tiff',
                '.tif': 'image/tiff',
                '.webp': 'image/webp'
            }
            mimetype = mimetype_map.get(ext, 'application/octet-stream')

            logger.info(f"Serving original image to device {device_id}: {file_path} ({file_size:,} bytes)")

            # Send file
            return send_file(
                file_path,
                mimetype=mimetype,
                as_attachment=False,
                download_name=Path(file_path).name
            )

    except Exception as e:
        logger.error(f"Error serving image: {e}", exc_info=True)
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/generate-token', methods=['GET'])
def generate_token():
    """
    Generate a token for a device_id (valid for 30 minutes)

    Query parameters:
    - device_id: Device ID

    Example:
    - /generate-token?device_id=122
    """
    try:
        device_id = request.args.get('device_id')

        if not device_id:
            return jsonify({'error': 'Missing device_id parameter'}), 400

        try:
            device_id = int(device_id)
        except ValueError:
            return jsonify({'error': 'Invalid device_id'}), 400

        # Verify device exists
        device = get_device_by_id(device_id)
        if not device:
            return jsonify({'error': 'Device not found'}), 404

        token, time_window = create_token(device_id)
        expires_at = time_window + timedelta(minutes=TOKEN_VALIDITY_MINUTES)

        logger.info(f"Generated token for device {device_id}, valid until {expires_at.strftime('%Y-%m-%d %H:%M:%S UTC')}")

        return jsonify({
            'device_id': device_id,
            'serial_id': device['serial_id'],
            'token': token,
            'generated_at': time_window.strftime('%Y-%m-%d %H:%M:%S UTC'),
            'expires_at': expires_at.strftime('%Y-%m-%d %H:%M:%S UTC'),
            'valid_for_minutes': TOKEN_VALIDITY_MINUTES
        }), 200

    except Exception as e:
        logger.error(f"Error generating token: {e}", exc_info=True)
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({'status': 'healthy', 'service': 'image-server'}), 200

@app.route('/encode', methods=['GET'])
def encode_path():
    """
    Helper endpoint to encode a path

    Query parameters:
    - path: File path to encode
    - encoding: 'base64' or 'url' (default: 'both')

    Example:
    - /encode?path=/mnt/disk1/media/LAWA_01_WTP/Area_1/1729701045123.jpg
    """
    try:
        file_path = request.args.get('path')
        encoding = request.args.get('encoding', 'both')

        if not file_path:
            return jsonify({'error': 'Missing path parameter'}), 400

        result = {'original': file_path}

        if encoding in ['url', 'both']:
            from urllib.parse import quote
            result['url_encoded'] = quote(file_path, safe='')

        if encoding in ['base64', 'both']:
            result['base64_encoded'] = base64.b64encode(file_path.encode('utf-8')).decode('utf-8')

        return jsonify(result), 200

    except Exception as e:
        logger.error(f"Error encoding path: {e}", exc_info=True)
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/debug', methods=['GET'])
def debug_path():
    """Debug endpoint to check path validation (requires authentication)"""
    try:
        encoded_path = request.args.get('path')
        device_id = request.args.get('device_id')
        provided_token = request.args.get('token')
        encoding = request.args.get('encoding', 'url')

        if not all([encoded_path, device_id, provided_token]):
            return jsonify({'error': 'Missing required parameters'}), 400

        device_id = int(device_id)

        # Get current time window info
        current_window = get_current_time_window()
        expires_at = current_window + timedelta(minutes=TOKEN_VALIDITY_MINUTES)

        # Validate token
        token_valid = validate_token(device_id, provided_token)

        # Decode path
        if encoding == 'base64':
            file_path = base64.b64decode(encoded_path).decode('utf-8')
        else:
            file_path = unquote(encoded_path)

        # Handle shortened path format
        original_path = file_path
        if file_path and file_path[0].isdigit():
            file_path = f"/mnt/disk{file_path}"

        # Debug info
        abs_path = Path(file_path).resolve()

        # Check fallback disk paths
        fallback_info = None
        if '/mnt/disk1/' in file_path:
            fallback_path = file_path.replace('/mnt/disk1/', '/mnt/disk2/')
            fallback_info = {
                'fallback_disk': 'disk2',
                'fallback_path': fallback_path,
                'fallback_exists': os.path.isfile(fallback_path)
            }
        elif '/mnt/disk3/' in file_path:
            fallback_path = file_path.replace('/mnt/disk3/', '/mnt/disk4/')
            fallback_info = {
                'fallback_disk': 'disk4',
                'fallback_path': fallback_path,
                'fallback_exists': os.path.isfile(fallback_path)
            }

        result = {
            'original_param': encoded_path,
            'decoded_path': original_path,
            'converted_path': file_path if original_path != file_path else None,
            'absolute_path': str(abs_path),
            'exists': os.path.isfile(file_path),
            'fallback_info': fallback_info,
            'is_safe': is_safe_path(file_path),
            'is_allowed_ext': is_allowed_extension(file_path),
            'token_valid': token_valid,
            'device_id': device_id,
            'current_time_window': current_window.strftime('%Y-%m-%d %H:%M:%S UTC'),
            'token_expires_at': expires_at.strftime('%Y-%m-%d %H:%M:%S UTC'),
            'allowed_base_paths': ALLOWED_BASE_PATHS
        }

        # Check each base path
        checks = {}
        for base_path in ALLOWED_BASE_PATHS:
            resolved_base = str(Path(base_path).resolve())
            starts_with = str(abs_path).startswith(resolved_base)
            checks[base_path] = {
                'resolved': resolved_base,
                'matches': starts_with
            }
        result['base_path_checks'] = checks

        return jsonify(result), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.errorhandler(404)
def not_found(e):
    return jsonify({'error': 'Endpoint not found'}), 404

@app.errorhandler(500)
def internal_error(e):
    logger.error(f"Internal server error: {e}", exc_info=True)
    return jsonify({'error': 'Internal server error'}), 500

if __name__ == '__main__':
    # Get port from environment or default to 80
    port = int(os.environ.get('PORT', 80))

    logger.info("=" * 60)
    logger.info(f"Starting Image Server on port {port}")
    logger.info(f"Token validity: {TOKEN_VALIDITY_MINUTES} minutes")
    logger.info(f"Allowed base paths: {ALLOWED_BASE_PATHS}")
    logger.info(f"Token keyword: {TOKEN_KEYWORD}")
    logger.info("=" * 60)

    # Run on port 8080 (no sudo needed)
    app.run(host='0.0.0.0', port=port, debug=False)
