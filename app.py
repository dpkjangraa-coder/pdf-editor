import fitz
import base64
import io
import math
from flask import Flask, request, send_file, jsonify

app = Flask(__name__, static_folder='public', static_url_path='')

@app.route('/')
def index():
    return app.send_static_file('index.html')

@app.route('/get-page-image', methods=['POST'])
def get_page_image():
    try:
        data = request.get_json()
        pdf_bytes = base64.b64decode(data['pdfBase64'])
        page_num = data['pageNum'] - 1
        angle = data.get('angle', 0)
        doc = fitz.open(stream=pdf_bytes, filetype='pdf')
        page = doc[page_num]
        if angle:
            page.set_rotation(angle)
        mat = fitz.Matrix(2, 2)
        pix = page.get_pixmap(matrix=mat, annots=False)
        for block in page.get_text('dict')['blocks']:
            if block.get('type') != 0:
                continue
            for line in block.get('lines', []):
                for span in line.get('spans', []):
                    if not span.get('text', '').strip():
                        continue
                    bbox = span['bbox']
                    x0 = int(bbox[0] * 2)
                    y0 = int(bbox[1] * 2)
                    x1 = int(bbox[2] * 2) + 4
                    y1 = int(bbox[3] * 2) + 2
                    pix.set_rect(fitz.IRect(x0, y0, x1, y1), (255, 255, 255))
        img_b64 = base64.b64encode(pix.tobytes('png')).decode()
        return jsonify({'image': img_b64, 'pageWidth': page.rect.width, 'pageHeight': page.rect.height})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/get-text', methods=['POST'])
def get_text():
    try:
        data = request.get_json()
        pdf_bytes = base64.b64decode(data['pdfBase64'])
        page_num = data['pageNum'] - 1
        angle = data.get('angle', 0)
        doc = fitz.open(stream=pdf_bytes, filetype='pdf')
        page = doc[page_num]
        if angle:
            page.set_rotation(angle)
        blocks = []
        for block in page.get_text('dict')['blocks']:
            if block.get('type') != 0:
                continue
            for line in block.get('lines', []):
                for span in line.get('spans', []):
                    text = span.get('text', '').strip()
                    if not text:
                        continue
                    color_int = span.get('color', 0)
                    r = ((color_int >> 16) & 0xFF) / 255.0
                    g = ((color_int >> 8) & 0xFF) / 255.0
                    b = (color_int & 0xFF) / 255.0
                    flags = span.get('flags', 0)
                    font = span.get('font', '')
                    bbox = span.get('bbox', [0, 0, 0, 0])
                    blocks.append({
                        'text': text, 'x': bbox[0], 'y': bbox[1], 'x1': bbox[2], 'y1': bbox[3],
                        'size': span.get('size', 12), 'bold': bool(flags & 16) or 'bold' in font.lower(),
                        'font': font, 'color': [r, g, b],
                    })
        return jsonify({'blocks': blocks, 'pageWidth': page.rect.width, 'pageHeight': page.rect.height})
    except Exception as e:
        return jsonify({'error': str(e), 'blocks': []}), 500

def rotate_point(px, py, cx, cy, rad):
    dx, dy = px - cx, py - cy
    return fitz.Point(cx + dx*math.cos(rad) - dy*math.sin(rad), cy + dx*math.sin(rad) + dy*math.cos(rad))

@app.route('/save-pdf', methods=['POST'])
def save_pdf():
    try:
        data = request.get_json()
        pdf_bytes = base64.b64decode(data['pdfBase64'])
        edits = data['edits']
        page_num = data['pageNum'] - 1
        images = data.get('images', [])
        text_boxes = data.get('textBoxes', [])
        shapes = data.get('shapes', [])
        display_w = data.get('displayW', 1)
        display_h = data.get('displayH', 1)
        doc = fitz.open(stream=pdf_bytes, filetype='pdf')
        page = doc[page_num]
        pdf_w = page.rect.width
        pdf_h = page.rect.height
        scale_x = pdf_w / display_w
        scale_y = pdf_h / display_h

        for edit in edits:
            if not edit.get('changed'):
                continue
            x0,y0,x1,y1,size = edit['x'],edit['y'],edit['x1'],edit['y1'],edit['size']
            page.draw_rect(fitz.Rect(x0-1,y0-1,x1+10,y1+1), color=(1,1,1), fill=(1,1,1))
            color = edit.get('color', [0,0,0])
            bold = edit.get('bold', False)
            fontname = 'hebo' if bold else 'helv'
            try:
                page.insert_text((x0, y0+size), edit['text'], fontsize=size*0.85, fontname=edit.get('font',fontname), color=tuple(color))
            except Exception:
                page.insert_text((x0, y0+size), edit['text'], fontsize=size*0.85, fontname=fontname, color=tuple(color))

        for img_data in images:
            img_src = img_data['src']
            ix,iy,iw,ih = img_data['x']*scale_x, img_data['y']*scale_y, img_data['w']*scale_x, img_data['h']*scale_y
            if ',' in img_src: img_src = img_src.split(',')[1]
            page.insert_image(fitz.Rect(ix,iy,ix+iw,iy+ih), stream=base64.b64decode(img_src))

        for tb in text_boxes:
            tx,ty,tw = tb['x']*scale_x, tb['y']*scale_y, tb['w']*scale_x
            text = tb.get('text','')
            font_size = tb.get('fontSize',16) * scale_y * 0.85
            fontname = 'hebo' if tb.get('bold',False) else 'helv'
            ch = tb.get('color','#000000').lstrip('#')
            tr,tg,tb_b = (int(ch[0:2],16)/255, int(ch[2:4],16)/255, int(ch[4:6],16)/255) if len(ch)==6 else (0,0,0)
            bg = tb.get('bgColor','transparent')
            if bg and bg != 'transparent':
                bh = bg.lstrip('#')
                if len(bh)==6:
                    br,bg_g,bb = int(bh[0:2],16)/255, int(bh[2:4],16)/255, int(bh[4:6],16)/255
                    page.draw_rect(fitz.Rect(tx-2,ty-2,tx+tw+2,ty+font_size*1.5), color=(br,bg_g,bb), fill=(br,bg_g,bb))
            try:
                page.insert_text((tx, ty+font_size), text, fontsize=font_size, fontname=fontname, color=(tr,tg,tb_b))
            except Exception:
                page.insert_text((tx, ty+font_size), text, fontsize=font_size, fontname='helv', color=(tr,tg,tb_b))

        for sh in shapes:
            sx,sy = sh['x']*scale_x, sh['y']*scale_y
            sw,sh_h = sh['w']*scale_x, sh['h']*scale_y
            stroke = sh.get('strokeW', 2)
            rotate_deg = sh.get('rotate', 0)
            ch = sh['color'].lstrip('#')
            r,g,b = (int(ch[0:2],16)/255, int(ch[2:4],16)/255, int(ch[4:6],16)/255) if len(ch)==6 else (0,0,0)
            cx,cy = sx+sw/2, sy+sh_h/2
            rad = math.radians(rotate_deg)
            shape_type = sh['type']

            if shape_type == 'rectangle':
                if rotate_deg == 0:
                    page.draw_rect(fitz.Rect(sx,sy,sx+sw,sy+sh_h), color=(r,g,b), width=stroke)
                else:
                    corners = [rotate_point(sx,sy,cx,cy,rad), rotate_point(sx+sw,sy,cx,cy,rad),
                               rotate_point(sx+sw,sy+sh_h,cx,cy,rad), rotate_point(sx,sy+sh_h,cx,cy,rad)]
                    page.draw_polyline(corners+[corners[0]], color=(r,g,b), width=stroke)
            elif shape_type == 'ellipse':
                if rotate_deg == 0:
                    page.draw_oval(fitz.Rect(sx,sy,sx+sw,sy+sh_h), color=(r,g,b), width=stroke)
                else:
                    pts = [rotate_point(cx+(sw/2)*math.cos(math.radians(i*10)), cy+(sh_h/2)*math.sin(math.radians(i*10)), cx,cy,rad) for i in range(37)]
                    page.draw_polyline(pts, color=(r,g,b), width=stroke)
            elif shape_type in ('line','arrow'):
                p1 = rotate_point(sx,sy,cx,cy,rad) if rotate_deg!=0 else fitz.Point(sx,sy)
                p2 = rotate_point(sx+sw,sy+sh_h,cx,cy,rad) if rotate_deg!=0 else fitz.Point(sx+sw,sy+sh_h)
                page.draw_line(p1, p2, color=(r,g,b), width=stroke)
                if shape_type == 'arrow':
                    ang = math.atan2(p2.y-p1.y, p2.x-p1.x)
                    aw = min(15, stroke*4)
                    page.draw_line(p2, fitz.Point(p2.x-aw*math.cos(ang-0.4), p2.y-aw*math.sin(ang-0.4)), color=(r,g,b), width=stroke)
                    page.draw_line(p2, fitz.Point(p2.x-aw*math.cos(ang+0.4), p2.y-aw*math.sin(ang+0.4)), color=(r,g,b), width=stroke)

        output = io.BytesIO()
        doc.save(output)
        output.seek(0)
        return send_file(output, mimetype='application/pdf', download_name='edited.pdf', as_attachment=True)
    except Exception as e:
        print(f"Error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/delete-page', methods=['POST'])
def delete_page():
    try:
        data = request.get_json()
        pdf_bytes = base64.b64decode(data['pdfBase64'])
        page_num = data['pageNum'] - 1
        doc = fitz.open(stream=pdf_bytes, filetype='pdf')
        if doc.page_count <= 1:
            return jsonify({'error': 'Sirf ek page hai!'}), 400
        doc.delete_page(page_num)
        output = io.BytesIO()
        doc.save(output)
        output.seek(0)
        return jsonify({'pdfBase64': base64.b64encode(output.read()).decode(), 'pageCount': doc.page_count})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/insert-page', methods=['POST'])
def insert_page():
    try:
        data = request.get_json()
        pdf_bytes = base64.b64decode(data['pdfBase64'])
        new_pdf_bytes = base64.b64decode(data['newPdfBase64'])
        after_page = data['afterPage']
        doc = fitz.open(stream=pdf_bytes, filetype='pdf')
        new_doc = fitz.open(stream=new_pdf_bytes, filetype='pdf')
        doc.insert_pdf(new_doc, from_page=0, to_page=0, start_at=after_page)
        output = io.BytesIO()
        doc.save(output)
        output.seek(0)
        return jsonify({'pdfBase64': base64.b64encode(output.read()).decode(), 'pageCount': doc.page_count})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(port=3000, debug=True)