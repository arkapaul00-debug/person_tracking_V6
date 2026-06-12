import os
import datetime
from fpdf import FPDF
from fpdf.enums import XPos, YPos
from django.conf import settings
from .models import ForensicCase, ReferenceImage
from .models_sighting import SuspectSighting

class ForensicReport(FPDF):
    def header(self):
        self.set_font('helvetica', 'B', 16)
        self.cell(0, 10, 'Forensic Analysis Report', align='C', new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(5)

    def footer(self):
        self.set_y(-15)
        self.set_font('helvetica', 'I', 8)
        self.cell(0, 10, f'Page {self.page_no()}', align='C')

def format_timestamp(seconds):
    return str(datetime.timedelta(seconds=int(seconds)))

def generate_forensic_report(case_id):
    """
    Generates a PDF report for a given ForensicCase.
    """
    try:
        case = ForensicCase.objects.get(id=case_id)
        sightings = SuspectSighting.objects.filter(case=case).order_by('start_time')
        references = ReferenceImage.objects.filter(case=case)
        
        pdf = ForensicReport()
        pdf.add_page()
        
        # Case Information
        pdf.set_font('Arial', 'B', 12)
        pdf.cell(0, 10, 'Case Details', 0, 1, 'L')
        pdf.set_font('Arial', '', 10)
        pdf.cell(0, 8, f'Case ID: {case.id}', 0, 1, 'L')
        pdf.cell(0, 8, f'Date: {case.created_at.strftime("%Y-%m-%d %H:%M:%S")}', 0, 1, 'L')
        
        video_name = "Unknown"
        if hasattr(case, 'video') and case.video.file:
            video_name = os.path.basename(case.video.file.name)
        pdf.cell(0, 8, f'Source Video: {video_name}', 0, 1, 'L')
        pdf.ln(5)
        
        # Target Images
        pdf.set_font('Arial', 'B', 12)
        pdf.cell(0, 10, 'Target Image(s)', 0, 1, 'L')
        
        if references.exists():
            x_start = 10
            y_start = pdf.get_y()
            img_width = 40
            for i, ref in enumerate(references):
                if ref.file:
                    img_path = ref.file.path
                    if os.path.exists(img_path):
                        # Add image. Adjust X position for multiple images if they fit
                        pdf.image(img_path, x=x_start + (i * (img_width + 5)), y=y_start, w=img_width)
            
            # Move cursor below images
            pdf.set_y(y_start + img_width + 10)
        else:
            pdf.set_font('Arial', '', 10)
            pdf.cell(0, 8, 'No reference images provided.', 0, 1, 'L')
            pdf.ln(5)
            
        # Detection Results
        pdf.set_font('Arial', 'B', 12)
        pdf.cell(0, 10, 'Detection Summary', 0, 1, 'L')
        
        if sightings.exists():
            pdf.set_font('Arial', '', 10)
            pdf.cell(0, 8, 'The target was detected in the following segments:', 0, 1, 'L')
            pdf.ln(2)
            
            # Table Header
            pdf.set_font('Arial', 'B', 10)
            pdf.cell(40, 8, 'Start Time', 1, 0, 'C')
            pdf.cell(40, 8, 'End Time', 1, 0, 'C')
            pdf.cell(40, 8, 'Duration (s)', 1, 1, 'C')
            
            pdf.set_font('Arial', '', 10)
            total_duration = 0
            for s in sightings:
                duration = s.end_time - s.start_time
                total_duration += duration
                pdf.cell(40, 8, format_timestamp(s.start_time), 1, 0, 'C')
                pdf.cell(40, 8, format_timestamp(s.end_time), 1, 0, 'C')
                pdf.cell(40, 8, f'{duration:.2f}', 1, 1, 'C')
            
            pdf.ln(5)
            pdf.set_font('Arial', 'B', 11)
            pdf.cell(0, 8, f'Total Detection Duration: {total_duration:.2f} seconds', 0, 1, 'L')
        else:
            pdf.set_font('Arial', 'B', 12)
            pdf.set_text_color(200, 0, 0)
            pdf.cell(0, 10, 'TARGET NOT PRESENT IN THE VIDEO FEED', 0, 1, 'L')
            pdf.set_text_color(0, 0, 0)

        # Output Path
        report_filename = f"report_{case_id}.pdf"
        report_dir = os.path.join(settings.MEDIA_ROOT, 'outputs', 'reports')
        os.makedirs(report_dir, exist_ok=True)
        report_abs_path = os.path.join(report_dir, report_filename)
        
        pdf.output(report_abs_path)
        
        # Save to DB
        case.report_pdf = f"outputs/reports/{report_filename}"
        case.save()
        
        return report_abs_path

    except Exception as e:
        print(f"Error generating report: {e}")
        import traceback
        traceback.print_exc()
        return None
