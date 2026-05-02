from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import os, uuid, threading, time, shutil, zipfile

app = Flask(__name__)
CORS(app)

BASE = os.path.dirname(__file__)
UPL = os.path.join(BASE, 'uploads')
OUT = os.path.join(BASE, 'outputs')
os.makedirs(UPL, exist_ok=True)
os.makedirs(OUT, exist_ok=True)
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024

def cleanup():
    while True:
        now = time.time()
        for folder in [UPL, OUT]:
            for f in os.listdir(folder):
                fp = os.path.join(folder, f)
                try:
                    if os.path.isfile(fp) and now - os.path.getmtime(fp) > 3600:
                        os.remove(fp)
                    elif os.path.isdir(fp) and now - os.path.getmtime(fp) > 3600:
                        shutil.rmtree(fp)
                except: pass
        time.sleep(300)

threading.Thread(target=cleanup, daemon=True).start()

def save_file(f, suffix='.pdf'):
    name = str(uuid.uuid4()) + suffix
    path = os.path.join(UPL, name)
    f.save(path)
    return path

def out_path(suffix):
    return os.path.join(OUT, str(uuid.uuid4()) + suffix)

@app.route('/api/health')
def health():
    return jsonify({'status': 'ok'})

# ── PDF: COMPRESS ──
@app.route('/api/compress', methods=['POST'])
def compress():
    if 'file' not in request.files: return jsonify({'error': 'No file'}), 400
    inp = save_file(request.files['file'])
    quality = request.form.get('quality', 'medium')
    outp = out_path('_compressed.pdf')
    try:
        from pypdf import PdfReader, PdfWriter
        reader = PdfReader(inp)
        writer = PdfWriter()
        for page in reader.pages:
            if quality in ('low', 'medium'):
                try: page.compress_content_streams()
                except: pass
            writer.add_page(page)
        writer.add_metadata({})
        with open(outp, 'wb') as f: writer.write(f)
        orig = os.path.getsize(inp)
        new = os.path.getsize(outp)
        did = str(uuid.uuid4())
        final = os.path.join(OUT, did + '_compressed.pdf')
        shutil.move(outp, final)
        return jsonify({'success': True, 'download_id': did + '_compressed', 'filename': 'compressed.pdf',
                        'original_size': orig, 'new_size': new,
                        'reduction': round((1 - new/orig)*100, 1)})
    except Exception as e: return jsonify({'error': str(e)}), 500

# ── PDF: MERGE ──
@app.route('/api/merge', methods=['POST'])
def merge():
    files = request.files.getlist('files')
    if len(files) < 2: return jsonify({'error': 'Need at least 2 files'}), 400
    from pypdf import PdfWriter, PdfReader
    writer = PdfWriter()
    for f in files:
        p = save_file(f)
        for page in PdfReader(p).pages: writer.add_page(page)
    did = str(uuid.uuid4())
    outp = os.path.join(OUT, did + '_merged.pdf')
    with open(outp, 'wb') as f: writer.write(f)
    return jsonify({'success': True, 'download_id': did + '_merged', 'filename': 'merged.pdf'})

# ── PDF: SPLIT ──
@app.route('/api/split', methods=['POST'])
def split():
    if 'file' not in request.files: return jsonify({'error': 'No file'}), 400
    inp = save_file(request.files['file'])
    mode = request.form.get('mode', 'all')
    pages_str = request.form.get('pages', '')
    from pypdf import PdfReader, PdfWriter
    reader = PdfReader(inp)
    total = len(reader.pages)
    if mode == 'range' and pages_str:
        nums = []
        for part in pages_str.split(','):
            part = part.strip()
            if '-' in part:
                s, e = part.split('-')
                nums.extend(range(int(s)-1, min(int(e), total)))
            else:
                nums.append(int(part)-1)
    else:
        nums = list(range(total))
    did = str(uuid.uuid4())
    tmpdir = os.path.join(OUT, did + '_split')
    os.makedirs(tmpdir, exist_ok=True)
    files_out = []
    for i, pn in enumerate(nums):
        if 0 <= pn < total:
            w = PdfWriter(); w.add_page(reader.pages[pn])
            fp = os.path.join(tmpdir, f'page_{pn+1}.pdf')
            with open(fp, 'wb') as f: w.write(f)
            files_out.append(fp)
    zip_path = os.path.join(OUT, did + '_split.zip')
    with zipfile.ZipFile(zip_path, 'w') as zf:
        for fp in files_out: zf.write(fp, os.path.basename(fp))
    return jsonify({'success': True, 'download_id': did + '_split', 'filename': 'pages.zip', 'pages_count': len(files_out)})

# ── PDF: ROTATE ──
@app.route('/api/rotate', methods=['POST'])
def rotate():
    if 'file' not in request.files: return jsonify({'error': 'No file'}), 400
    inp = save_file(request.files['file'])
    angle = int(request.form.get('angle', 90))
    from pypdf import PdfReader, PdfWriter
    writer = PdfWriter()
    for page in PdfReader(inp).pages:
        page.rotate(angle); writer.add_page(page)
    did = str(uuid.uuid4())
    outp = os.path.join(OUT, did + '_rotated.pdf')
    with open(outp, 'wb') as f: writer.write(f)
    return jsonify({'success': True, 'download_id': did + '_rotated', 'filename': 'rotated.pdf'})

# ── PDF: PROTECT ──
@app.route('/api/protect', methods=['POST'])
def protect():
    if 'file' not in request.files: return jsonify({'error': 'No file'}), 400
    pw = request.form.get('password', '')
    if not pw: return jsonify({'error': 'Password required'}), 400
    inp = save_file(request.files['file'])
    from pypdf import PdfReader, PdfWriter
    writer = PdfWriter()
    for page in PdfReader(inp).pages: writer.add_page(page)
    writer.encrypt(pw)
    did = str(uuid.uuid4())
    outp = os.path.join(OUT, did + '_protected.pdf')
    with open(outp, 'wb') as f: writer.write(f)
    return jsonify({'success': True, 'download_id': did + '_protected', 'filename': 'protected.pdf'})

# ── PDF: UNLOCK ──
@app.route('/api/unlock', methods=['POST'])
def unlock():
    if 'file' not in request.files: return jsonify({'error': 'No file'}), 400
    pw = request.form.get('password', '')
    inp = save_file(request.files['file'])
    from pypdf import PdfReader, PdfWriter
    reader = PdfReader(inp)
    if reader.is_encrypted:
        ok = reader.decrypt(pw)
        if not ok: return jsonify({'error': 'Incorrect password'}), 400
    writer = PdfWriter()
    for page in reader.pages: writer.add_page(page)
    did = str(uuid.uuid4())
    outp = os.path.join(OUT, did + '_unlocked.pdf')
    with open(outp, 'wb') as f: writer.write(f)
    return jsonify({'success': True, 'download_id': did + '_unlocked', 'filename': 'unlocked.pdf'})

# ── PDF: WATERMARK ──
@app.route('/api/watermark', methods=['POST'])
def watermark():
    if 'file' not in request.files: return jsonify({'error': 'No file'}), 400
    text = request.form.get('text', 'CONFIDENTIAL')
    opacity = float(request.form.get('opacity', 0.3))
    inp = save_file(request.files['file'])
    from pypdf import PdfReader, PdfWriter
    from reportlab.pdfgen import canvas
    import io
    reader = PdfReader(inp)
    writer = PdfWriter()
    for page in reader.pages:
        w = float(page.mediabox.width)
        h = float(page.mediabox.height)
        pkt = io.BytesIO()
        c = canvas.Canvas(pkt, pagesize=(w, h))
        sz = max(20, int(w/12))
        c.setFont('Helvetica-Bold', sz)
        c.setFillColorRGB(0.5, 0.5, 0.5, alpha=opacity)
        c.saveState(); c.translate(w/2, h/2); c.rotate(45)
        tw = c.stringWidth(text, 'Helvetica-Bold', sz)
        c.drawString(-tw/2, 0, text); c.restoreState(); c.save()
        pkt.seek(0)
        from pypdf import PdfReader as PR
        wm = PR(pkt).pages[0]
        page.merge_page(wm); writer.add_page(page)
    did = str(uuid.uuid4())
    outp = os.path.join(OUT, did + '_watermarked.pdf')
    with open(outp, 'wb') as f: writer.write(f)
    return jsonify({'success': True, 'download_id': did + '_watermarked', 'filename': 'watermarked.pdf'})

# ── IMAGES → PDF ──
@app.route('/api/img-to-pdf', methods=['POST'])
def img_to_pdf():
    files = request.files.getlist('files')
    if not files: return jsonify({'error': 'No files'}), 400
    from PIL import Image
    imgs = []
    for f in files:
        ext = os.path.splitext(f.filename)[1].lower() or '.jpg'
        p = save_file(f, ext)
        imgs.append(Image.open(p).convert('RGB'))
    did = str(uuid.uuid4())
    outp = os.path.join(OUT, did + '_converted.pdf')
    imgs[0].save(outp, save_all=True, append_images=imgs[1:])
    return jsonify({'success': True, 'download_id': did + '_converted', 'filename': 'images.pdf'})

# ── PDF → IMAGES ──
@app.route('/api/pdf-to-img', methods=['POST'])
def pdf_to_img():
    if 'file' not in request.files: return jsonify({'error': 'No file'}), 400
    fmt = request.form.get('format', 'jpg')
    inp = save_file(request.files['file'])
    did = str(uuid.uuid4())
    tmpdir = os.path.join(OUT, did + '_imgs')
    os.makedirs(tmpdir, exist_ok=True)
    from pypdf import PdfReader
    from PIL import Image, ImageDraw
    reader = PdfReader(inp)
    files_out = []
    for i, page in enumerate(reader.pages):
        w = int(float(page.mediabox.width))
        h = int(float(page.mediabox.height))
        img = Image.new('RGB', (max(w,100), max(h,100)), 'white')
        draw = ImageDraw.Draw(img)
        draw.text((max(w,100)//2-40, max(h,100)//2), f'Page {i+1}', fill='gray')
        fp = os.path.join(tmpdir, f'page_{i+1}.{fmt}')
        img.save(fp)
        files_out.append(fp)
    zip_path = os.path.join(OUT, did + '_imgs.zip')
    with zipfile.ZipFile(zip_path, 'w') as zf:
        for fp in files_out: zf.write(fp, os.path.basename(fp))
    return jsonify({'success': True, 'download_id': did + '_imgs', 'filename': f'pdf_pages.zip', 'pages_count': len(files_out)})

# ── IMAGE: COMPRESS ──
@app.route('/api/compress-image', methods=['POST'])
def compress_image():
    if 'file' not in request.files: return jsonify({'error': 'No file'}), 400
    f = request.files['file']
    mode = request.form.get('mode', 'quality')
    quality = int(request.form.get('quality', 80))
    target_kb = int(request.form.get('target_kb', 200))
    dpi_val = int(request.form.get('dpi', 96))
    dpi_quality = int(request.form.get('dpi_quality', 85))
    fmt = request.form.get('format', 'same')
    max_width = request.form.get('max_width', '')

    ext = os.path.splitext(f.filename)[1].lower() or '.jpg'
    inp = save_file(f, ext)
    orig_size = os.path.getsize(inp)

    from PIL import Image
    img = Image.open(inp).convert('RGB')

    # Apply max width if set
    if max_width:
        mw = int(max_width)
        if img.width > mw:
            ratio = mw / img.width
            img = img.resize((mw, int(img.height * ratio)), Image.LANCZOS)

    # Determine output format
    if fmt == 'same':
        out_ext = ext if ext in ['.jpg','.jpeg','.png','.webp'] else '.jpg'
        save_fmt = 'JPEG' if out_ext in ['.jpg','.jpeg'] else out_ext[1:].upper()
    else:
        out_ext = '.' + fmt
        save_fmt = 'JPEG' if fmt == 'jpg' else fmt.upper()

    did = str(uuid.uuid4())
    outp = os.path.join(OUT, did + '_compressed' + out_ext)

    if mode == 'quality':
        if save_fmt == 'PNG':
            compress_level = max(0, min(9, int((100 - quality) / 11)))
            img.save(outp, 'PNG', optimize=True, compress_level=compress_level)
        else:
            img.save(outp, save_fmt if save_fmt != 'JPEG' else 'JPEG', quality=quality, optimize=True)

    elif mode == 'kb':
        target_bytes = target_kb * 1024
        # Binary search for the right quality
        lo, hi = 10, 95
        best_q = 75
        for _ in range(10):
            mid = (lo + hi) // 2
            import io
            buf = io.BytesIO()
            img.save(buf, 'JPEG', quality=mid, optimize=True)
            sz = buf.tell()
            if sz <= target_bytes:
                best_q = mid; lo = mid + 1
            else:
                hi = mid - 1
        img.save(outp, 'JPEG' if save_fmt=='JPEG' else save_fmt, quality=best_q, optimize=True)

    elif mode == 'dpi':
        # Resize image based on DPI change
        # Get original dimensions and recalculate at new DPI
        orig_dpi = img.info.get('dpi', (72, 72))
        if isinstance(orig_dpi, (int, float)):
            orig_dpi = (orig_dpi, orig_dpi)
        orig_dpi_x = orig_dpi[0] if orig_dpi[0] > 0 else 72
        scale = dpi_val / orig_dpi_x
        new_w = max(1, int(img.width * scale))
        new_h = max(1, int(img.height * scale))
        img = img.resize((new_w, new_h), Image.LANCZOS)
        img.save(outp, save_fmt if save_fmt != 'JPEG' else 'JPEG',
                 quality=dpi_quality, optimize=True, dpi=(dpi_val, dpi_val))

    new_size = os.path.getsize(outp)
    out_name = 'compressed' + out_ext
    return jsonify({
        'success': True,
        'download_id': did + '_compressed',
        'filename': out_name,
        'original_size': orig_size,
        'new_size': new_size,
        'reduction': round((1 - new_size/orig_size)*100, 1)
    })

# ── IMAGE: RESIZE ──
@app.route('/api/resize-image', methods=['POST'])
def resize_image():
    if 'file' not in request.files: return jsonify({'error': 'No file'}), 400
    f = request.files['file']
    mode = request.form.get('mode', 'px')
    keep_ratio = request.form.get('keep_ratio', '1') == '1'
    ext = os.path.splitext(f.filename)[1].lower() or '.jpg'
    inp = save_file(f, ext)
    from PIL import Image
    img = Image.open(inp).convert('RGB')
    ow, oh = img.width, img.height
    if mode == 'pct':
        pct = float(request.form.get('percent', 50)) / 100
        nw, nh = int(ow*pct), int(oh*pct)
    else:
        nw = int(request.form.get('width', 0) or ow)
        nh_raw = request.form.get('height', '') or ''
        if nh_raw and not keep_ratio:
            nh = int(nh_raw)
        elif keep_ratio:
            nh = int(oh * (nw / ow))
        else:
            nh = oh
    img = img.resize((max(1,nw), max(1,nh)), Image.LANCZOS)
    did = str(uuid.uuid4())
    outp = os.path.join(OUT, did + '_resized' + ext)
    save_fmt = 'JPEG' if ext in ['.jpg','.jpeg'] else ext[1:].upper()
    img.save(outp, save_fmt, quality=90, optimize=True)
    orig = os.path.getsize(inp); new = os.path.getsize(outp)
    return jsonify({'success': True, 'download_id': did + '_resized', 'filename': 'resized' + ext,
                    'original_size': orig, 'new_size': new, 'reduction': round((1-new/orig)*100,1)})

# ── IMAGE: CONVERT ──
@app.route('/api/convert-image', methods=['POST'])
def convert_image():
    files = request.files.getlist('files')
    if not files: return jsonify({'error': 'No files'}), 400
    out_fmt = request.form.get('format', 'jpg').lower()
    from PIL import Image
    did = str(uuid.uuid4())
    if len(files) == 1:
        f = files[0]
        ext = os.path.splitext(f.filename)[1].lower() or '.jpg'
        inp = save_file(f, ext)
        img = Image.open(inp)
        if out_fmt in ['jpg','jpeg']:
            img = img.convert('RGB')
            outp = os.path.join(OUT, did + '_converted.jpg')
            img.save(outp, 'JPEG', quality=92)
        else:
            outp = os.path.join(OUT, did + '_converted.' + out_fmt)
            img.save(outp, out_fmt.upper())
        return jsonify({'success': True, 'download_id': did + '_converted', 'filename': 'converted.' + out_fmt})
    else:
        tmpdir = os.path.join(OUT, did + '_converted')
        os.makedirs(tmpdir, exist_ok=True)
        for fi in files:
            ext = os.path.splitext(fi.filename)[1].lower() or '.jpg'
            inp = save_file(fi, ext)
            base = os.path.splitext(fi.filename)[0]
            img = Image.open(inp)
            if out_fmt in ['jpg','jpeg']: img = img.convert('RGB')
            outp = os.path.join(tmpdir, base + '.' + out_fmt)
            img.save(outp, out_fmt.upper() if out_fmt != 'jpg' else 'JPEG')
        zip_path = os.path.join(OUT, did + '_converted.zip')
        with zipfile.ZipFile(zip_path, 'w') as zf:
            for fn in os.listdir(tmpdir): zf.write(os.path.join(tmpdir,fn), fn)
        return jsonify({'success': True, 'download_id': did + '_converted', 'filename': 'converted_images.zip'})

# ── DOWNLOAD ──
@app.route('/api/download/<did>')
def download(did):
    for ext in ['.zip', '.pdf', '.jpg', '.jpeg', '.png', '.webp', '.bmp', '.gif']:
        fp = os.path.join(OUT, did + ext)
        if os.path.exists(fp):
            return send_file(fp, as_attachment=True)
    return jsonify({'error': 'File not found or expired'}), 404

if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=5000)
