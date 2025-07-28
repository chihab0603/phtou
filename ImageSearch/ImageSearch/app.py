import os
import logging
import io
import requests
from flask import Flask, render_template, request, flash, redirect, url_for, send_file, jsonify
from duckduckgo_search import DDGS
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from PIL import Image
import zipfile
from datetime import datetime

# Configure logging
logging.basicConfig(level=logging.DEBUG)

# Create the Flask app
app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "fallback_secret_key_for_development")

@app.route('/')
def index():
    """Display the search form"""
    return render_template('index.html')

@app.route('/search', methods=['POST'])
def search():
    """Handle image search requests"""
    query = request.form.get('query', '').strip()
    
    if not query:
        flash('يرجى إدخال كلمة بحث', 'warning')
        return redirect(url_for('index'))
    
    try:
        # Initialize DuckDuckGo search
        ddgs = DDGS()
        
        # Search for images (limit to 20 results for better performance)
        images = list(ddgs.images(
            keywords=query,
            max_results=20,
            safesearch='moderate'
        ))
        
        if not images:
            flash(f'لم يتم العثور على صور لـ "{query}"', 'info')
            return redirect(url_for('index'))
        
        return render_template('results.html', images=images, query=query)
        
    except Exception as e:
        app.logger.error(f"Error searching for images: {str(e)}")
        flash('حدث خطأ أثناء البحث عن الصور. يرجى المحاولة مرة أخرى.', 'danger')
        return redirect(url_for('index'))

@app.route('/refresh_search', methods=['POST'])
def refresh_search():
    """Refresh search results with new images"""
    query = request.form.get('query', '').strip()
    
    if not query:
        return jsonify({'error': 'Query is required'}), 400
    
    try:
        # Initialize DuckDuckGo search
        ddgs = DDGS()
        
        # Search for images with different parameters to get fresh results
        images = list(ddgs.images(
            keywords=query,
            max_results=20,
            safesearch='moderate'
        ))
        
        if not images:
            return jsonify({'error': f'No images found for "{query}"'}), 404
        
        return jsonify({
            'images': images,
            'query': query,
            'count': len(images)
        })
        
    except Exception as e:
        app.logger.error(f"Error refreshing search: {str(e)}")
        return jsonify({'error': 'An error occurred while refreshing images'}), 500

@app.route('/load_more_images', methods=['POST'])
def load_more_images():
    """Load more images for the same query"""
    data = request.get_json() or {}
    query = data.get('query', '').strip()
    current_count = data.get('current_count', 0)
    
    if not query:
        return jsonify({'error': 'Query is required'}), 400
    
    try:
        # Initialize DuckDuckGo search
        ddgs = DDGS()
        
        # Try different search strategies to get more varied results
        search_strategies = [
            query,
            f"{query} صور",
            f"{query} photos",
            f"{query} images",
            f"{query} HD",
            f"{query} pictures"
        ]
        
        new_images = []
        used_urls = set()
        
        # Get current images URLs to avoid duplicates
        current_images_data = data.get('current_images', [])
        for img in current_images_data:
            if isinstance(img, dict) and 'image' in img:
                used_urls.add(img['image'])
        
        for strategy in search_strategies:
            if len(new_images) >= 10:  # Stop when we have 10 images
                break
                
            try:
                search_results = list(ddgs.images(
                    keywords=strategy,
                    max_results=30,  # Get more to filter duplicates
                    safesearch='moderate'
                ))
                
                # Filter out duplicates and add new images
                for img in search_results:
                    if len(new_images) >= 10:  # Limit to 10 new images
                        break
                    if img.get('image') and img['image'] not in used_urls:
                        new_images.append(img)
                        used_urls.add(img['image'])
                        
            except Exception as search_error:
                app.logger.debug(f"Search strategy '{strategy}' failed: {str(search_error)}")
                continue
        
        # Limit to exactly 10 images
        new_images = new_images[:10]
        
        if not new_images:
            return jsonify({'error': 'لم يتوفر أي صور إضافية'}), 404
        
        return jsonify({
            'images': new_images,
            'query': query,
            'count': len(new_images)
        })
        
    except Exception as e:
        app.logger.error(f"Error loading more images: {str(e)}")
        return jsonify({'error': 'حدث خطأ أثناء تحميل المزيد من الصور'}), 500

def download_image(url):
    """Download image from URL and return PIL Image object"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        
        image = Image.open(io.BytesIO(response.content))
        # Convert to RGB if necessary
        if image.mode != 'RGB':
            image = image.convert('RGB')
        return image
    except Exception as e:
        app.logger.error(f"Error downloading image from {url}: {str(e)}")
        return None

@app.route('/download_single/<path:image_url>')
def download_single_image(image_url):
    """Download a single image"""
    try:
        image = download_image(image_url)
        if image is None:
            flash('فشل في تحميل الصورة', 'danger')
            return redirect(request.referrer or url_for('index'))
        
        # Save image to memory
        img_io = io.BytesIO()
        image.save(img_io, 'JPEG', quality=95)
        img_io.seek(0)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"image_{timestamp}.jpg"
        
        return send_file(
            img_io,
            mimetype='image/jpeg',
            as_attachment=True,
            download_name=filename
        )
        
    except Exception as e:
        app.logger.error(f"Error downloading single image: {str(e)}")
        flash('فشل في تحميل الصورة', 'danger')
        return redirect(request.referrer or url_for('index'))

@app.route('/download_images_zip', methods=['POST'])
def download_images_zip():
    """Download selected images as ZIP file"""
    try:
        data = request.get_json() or {}
        image_urls = data.get('image_urls', [])
        query = data.get('query', 'images')
        
        if not image_urls:
            return jsonify({'error': 'No images selected'}), 400
        
        # Create ZIP file in memory
        zip_io = io.BytesIO()
        
        with zipfile.ZipFile(zip_io, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            for i, url in enumerate(image_urls):
                image = download_image(url)
                if image:
                    img_io = io.BytesIO()
                    image.save(img_io, 'JPEG', quality=95)
                    zip_file.writestr(f"image_{i+1:02d}.jpg", img_io.getvalue())
        
        zip_io.seek(0)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{query}_{timestamp}.zip"
        
        return send_file(
            zip_io,
            mimetype='application/zip',
            as_attachment=True,
            download_name=filename
        )
        
    except Exception as e:
        app.logger.error(f"Error creating ZIP: {str(e)}")
        return jsonify({'error': 'Failed to create ZIP file'}), 500

def create_pdf_with_images(images, layout_type, query, stretch=False):
    """Create PDF with images in specified layout"""
    try:
        pdf_io = io.BytesIO()
        c = canvas.Canvas(pdf_io, pagesize=A4)
        width, height = A4
        
        # Define layouts
        layouts = {
            '1': {'cols': 1, 'rows': 1, 'per_page': 1},
            '2': {'cols': 2, 'rows': 1, 'per_page': 2},
            '4': {'cols': 2, 'rows': 2, 'per_page': 4},
            '6': {'cols': 2, 'rows': 3, 'per_page': 6},
            '8': {'cols': 2, 'rows': 4, 'per_page': 8}
        }
        
        layout = layouts.get(layout_type, layouts['4'])
        
        # Calculate image dimensions with proper margins
        margin = 10 if stretch else 20
        title_space = 0  # Remove title space completely
        
        # Available space for images
        available_width = width - (margin * 2)
        available_height = height - (margin * 2) - title_space
        
        # Calculate cell dimensions
        cell_width = available_width / layout['cols']
        cell_height = available_height / layout['rows']
        
        # Inner margin within each cell
        inner_margin = 5 if stretch else 10
        max_img_width = cell_width - (inner_margin * 2)
        max_img_height = cell_height - (inner_margin * 2)
        
        page_count = 0
        images_on_page = 0
        
        for i, image in enumerate(images):
            if images_on_page == 0:
                if page_count > 0:
                    c.showPage()
                page_count += 1
                # No title added to pages anymore
            
            # Calculate position
            col = images_on_page % layout['cols']
            row = images_on_page // layout['cols']
            
            # Cell position
            cell_x = margin + col * cell_width
            cell_y = height - margin - title_space - (row + 1) * cell_height
            
            if stretch:
                # Stretch mode: fill the entire cell
                new_width = max_img_width
                new_height = max_img_height
                img_x = cell_x + inner_margin
                img_y = cell_y + inner_margin
            else:
                # Normal mode: maintain aspect ratio
                aspect_ratio = image.width / image.height
                
                # Fit image within cell while maintaining aspect ratio
                if aspect_ratio > max_img_width / max_img_height:
                    # Image is wider relative to cell - fit to width
                    new_width = max_img_width
                    new_height = max_img_width / aspect_ratio
                else:
                    # Image is taller relative to cell - fit to height
                    new_height = max_img_height
                    new_width = max_img_height * aspect_ratio
                
                # Center image within cell
                img_x = cell_x + (cell_width - new_width) / 2
                img_y = cell_y + (cell_height - new_height) / 2
            
            # Draw cell border (optional - for debugging)
            # c.setStrokeColorRGB(0.8, 0.8, 0.8)
            # c.rect(cell_x + inner_margin, cell_y + inner_margin, 
            #        cell_width - 2*inner_margin, cell_height - 2*inner_margin)
            
            # Add image to PDF
            img_io = io.BytesIO()
            image.save(img_io, 'JPEG', quality=90)
            img_io.seek(0)
            
            c.drawImage(
                ImageReader(img_io),
                img_x, img_y,
                new_width, new_height
            )
            
            images_on_page += 1
            
            if images_on_page >= layout['per_page']:
                images_on_page = 0
        
        c.save()
        pdf_io.seek(0)
        
        return pdf_io
        
    except Exception as e:
        app.logger.error(f"Error creating PDF: {str(e)}")
        return None

@app.route('/download_pdf', methods=['POST'])
def download_pdf():
    """Download selected images as PDF with specified layout"""
    try:
        data = request.get_json() or {}
        image_urls = data.get('image_urls', [])
        layout_type = data.get('layout', '4')
        stretch = data.get('stretch', False)
        query = data.get('query', 'images')
        
        if not image_urls:
            return jsonify({'error': 'No images selected'}), 400
        
        # Download images
        images = []
        for url in image_urls:
            image = download_image(url)
            if image:
                images.append(image)
        
        if not images:
            return jsonify({'error': 'Failed to download any images'}), 400
        
        # Create PDF
        pdf_io = create_pdf_with_images(images, layout_type, query, stretch)
        
        if pdf_io is None:
            return jsonify({'error': 'Failed to create PDF'}), 500
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{query}_{layout_type}images_{timestamp}.pdf"
        
        return send_file(
            pdf_io,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=filename
        )
        
    except Exception as e:
        app.logger.error(f"Error creating PDF download: {str(e)}")
        return jsonify({'error': 'Failed to create PDF'}), 500

@app.errorhandler(404)
def not_found(error):
    """Handle 404 errors"""
    return render_template('index.html'), 404

@app.errorhandler(500)
def internal_error(error):
    """Handle 500 errors"""
    app.logger.error(f"Internal server error: {str(error)}")
    flash('An internal error occurred. Please try again.', 'danger')
    return render_template('index.html'), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
