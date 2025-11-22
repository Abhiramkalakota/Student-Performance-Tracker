# 1. Import Dependencies
import os
import csv
import json
import traceback
import functools
from flask import Flask, request, redirect, url_for, jsonify, render_template, session, flash, make_response
from werkzeug.utils import secure_filename

# 2. Initialize Flask App
app = Flask(__name__)
# REQUIRED for sessions (user login)
app.secret_key = 'your-super-secret-key-change-this'

# Configuration for file uploads
UPLOAD_FOLDER = 'uploads'
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER


def no_cache(view):
    """Decorator to add headers to prevent caching."""
    @functools.wraps(view)
    def wrapped_view(**kwargs):
        response = make_response(view(**kwargs))
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '-1' # Or 0
        return response
    return wrapped_view


# =================================================================
# 3. DYNAMIC DATABASE (Python Dictionaries)
# =================================================================

faculty_users = {
    # Faculty login
    "prof_davis": {"password": "securepass", "role": "faculty", "name": "Prof. Davis"}
}

# These dictionaries will be populated by the admin's CSV uploads.
student_login_data = {}
student_profile_data = {}
student_grades_data = {}
student_attendance_data = {}

# Courses in-memory store and CSV constants (used by course management routes)
course_data = {}
COURSES_CSV = 'courses.csv'
COURSE_HEADERS = ['courseCode', 'courseName', 'description', 'instructor', 'semester', 'credits', 'facultyId']

# Students CSV constants used across student creation, deletion and persistence logic
STUDENTS_CSV = 'students.csv'
STUDENT_HEADERS = [
    'studentId',
    'password',
    'firstName',
    'lastName',
    'email',
    'major',
    'program',
    'gpa',
    'enrollmentDate',
    'dob'
]

# Attendance CSV constants used for enrollment and attendance persistence
ATTENDANCE_CSV = 'attendance.csv'
ATTENDANCE_HEADERS = ['studentId', 'courseName', 'date', 'status', 'instructor']

def load_data_from_csv(filepath, data_dict, key_field, is_list=False):
    """Helper function to load CSV data into a dictionary."""
    try:
        # Check if file exists before trying to open
        if not os.path.isfile(filepath):
            print(f"Warning: CSV file not found at {filepath}. Skipping load.")
            return

        with open(filepath, mode='r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            # Check if file is empty or headers are missing
            if not reader.fieldnames:
                 print(f"Warning: CSV file {filepath} is empty or missing headers. Skipping load.")
                 return

            # Check if the required key_field exists in headers
            if key_field not in reader.fieldnames:
                print(f"Error: Required key field '{key_field}' not found in headers of {filepath}. Skipping load.")
                return

            data_dict.clear() # Clear old data before loading new
            for row in reader:
                # Ensure the key exists in the row before accessing
                if key_field not in row or row[key_field] is None:
                    print(f"Warning: Skipping row due to missing key field '{key_field}' in {filepath}: {row}")
                    continue

                key = row[key_field]
                if is_list:
                    # For grades/attendance, store a list of records per student
                    if key not in data_dict:
                        data_dict[key] = []
                    data_dict[key].append(row)
                else:
                    # For profiles/logins, store a single record
                    data_dict[key] = row
            print(f"Successfully loaded data from {filepath}")
    except Exception as e:
        print(f"Error loading {filepath}: {e}")

# =================================================================
# 4. SERVER ROUTES - CORE
# =================================================================

@app.route('/')
def index():
    # If already logged in, redirect to the correct dashboard
    if 'role' in session:
        if session['role'] == 'student':
            return redirect(url_for('student_dashboard'))
        elif session['role'] == 'faculty':
            return redirect(url_for('faculty_dashboard'))
    # If not logged in, show login page
    return render_template('login.html')

@app.route('/login', methods=['POST'])
def login():
    username = request.form.get('username')
    password = request.form.get('password')
    # NEW: Get the role selected by the user from the hidden input
    submitted_role = request.form.get('role', 'student') # Default to 'student' if missing

    session.clear() # Clear any old session

    login_successful = False
    error_message = f"Invalid {submitted_role} username or password"

    # Check FACULTY only if the submitted role is 'faculty'
    if submitted_role == 'faculty':
        if username in faculty_users and faculty_users[username]['password'] == password:
            session['user_id'] = username
            session['role'] = 'faculty'
            session['name'] = faculty_users[username]['name']
            login_successful = True
            print(f"Faculty login successful: {username}")
            return redirect(url_for('faculty_dashboard'))
        else:
             print(f"Faculty login failed for: {username}")

    # Check STUDENT only if the submitted role is 'student'
    elif submitted_role == 'student':
        if username in student_login_data and student_login_data[username]['password'] == password:
            session['user_id'] = username
            session['role'] = 'student'
            profile = student_profile_data.get(username, {})
            session['name'] = profile.get('firstName', 'Student')
            login_successful = True
            print(f"Student login successful: {username}")
            return redirect(url_for('student_dashboard'))
        else:
            print(f"Student login failed for: {username}")

    # If login failed after checking the specific role
    if not login_successful:
        flash(error_message, 'error')
        return redirect(url_for('index'))

    # Fallback (shouldn't normally be reached)
    flash('An unexpected login error occurred.', 'error')
    return redirect(url_for('index'))

@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'success')
    return redirect(url_for('index'))

# =================================================================
# 5. SERVER ROUTES - STUDENT (Analytics & Visualization)
# =================================================================
# --- Route to DISPLAY the full gradebook for a student ---
@app.route('/student_gradebook/<student_id>') # Check: Route path includes <student_id>
def student_gradebook(student_id):            # Check: Function name is student_gradebook
    """Displays the full gradebook for a specific student."""
    if not check_faculty_auth(): return redirect(url_for('index')) # Check authentication
    profile = student_profile_data.get(student_id) # Get student profile
    if not profile:
        flash(f"Student '{student_id}' not found.",'error') # Handle if student doesn't exist
        return redirect(url_for('manage_students'))

    grades = student_grades_data.get(student_id, []) # Get all grades for this student
    # Sort grades by date for display
    sorted_grades = sorted([g for g in grades if g.get('dateGraded')], key=lambda x:x['dateGraded'], reverse=True)

    # Render the specific gradebook template
    return render_template('student_gradebook.html',
                           user_name=session.get('name', '?'),
                           student=profile,
                           grades=sorted_grades)
def check_student_auth():
    """Helper to check if a user is a logged-in student."""
    return session.get('role') == 'student'

    
    # ... (rest of the delete logic) ...
    
    return redirect(url_for('manage_students'))
# --- NEW ROUTE: Display Edit Student Form ---
@app.route('/edit_student/<student_id>')
def edit_student(student_id):
    if not check_faculty_auth(): return redirect(url_for('index'))

    student_details = student_profile_data.get(student_id)
    if not student_details or not isinstance(student_details, dict):
        flash(f"Student with ID '{student_id}' not found.", 'error')
        return redirect(url_for('manage_students'))

    return render_template(
        'edit_student.html',
        user_name=session.get('name', '?'),
        student=student_details # Pass current student data to the form
    )

# --- NEW ROUTE: Handle Update Student Form Submission ---
@app.route('/update_student/<student_id>', methods=['POST'])
def update_student(student_id):
    if not check_faculty_auth(): return redirect(url_for('index'))

    original_student = student_profile_data.get(student_id)
    if not original_student or not isinstance(original_student, dict):
        flash(f"Student '{student_id}' not found for update.", 'error')
        return redirect(url_for('manage_students'))

    try:
        # 1. Get updated form data
        updated_data = {
            'studentId': student_id, # Keep original ID
            'firstName': request.form.get('firstName','').strip(),
            'lastName': request.form.get('lastName','').strip(),
            'email': request.form.get('email','').strip(),
            'dob': request.form.get('dob',''),
            'enrollmentDate': request.form.get('enrollmentDate',''),
            'major': request.form.get('major','Undeclared').strip(),
            'program': request.form.get('program','Undeclared').strip(),
            'gpa': request.form.get('gpa','0.0').strip(),
            # Handle password update
            'password': request.form.get('password') # Get new password (if entered)
        }
        confirm_password = request.form.get('confirmPassword')

        # 2. Basic Validation
        required = ['firstName', 'lastName', 'email', 'enrollmentDate', 'dob'] # Student ID is from URL
        if not all(updated_data.get(f) for f in required):
            flash('Required fields cannot be empty.', 'error')
            return redirect(url_for('edit_student', student_id=student_id))

        # Password validation (only if new password entered)
        if updated_data['password']: # If a new password was entered
            if updated_data['password'] != confirm_password:
                flash('New passwords do not match.', 'error')
                return redirect(url_for('edit_student', student_id=student_id))
        else:
            # If new password field is blank, keep the old password
            updated_data['password'] = original_student.get('password') # Keep existing password

        # 3. Update in-memory dictionaries
        student_profile_data[student_id] = updated_data # Update profile
        if student_id in student_login_data: # Update login if exists
            student_login_data[student_id]['password'] = updated_data['password']
        else: # Add login if somehow missing
             student_login_data[student_id] = {'password': updated_data['password'], 'role': 'student'}

        print(f"Updated student data in memory for {student_id}") # Debug print

        # 4. Rewrite the entire students.csv file
        all_students = list(student_profile_data.values())
        headers = STUDENT_HEADERS # Use defined headers
        try:
            # Determine headers robustly
            if os.path.isfile(STUDENTS_CSV) and os.path.getsize(STUDENTS_CSV) > 0:
                 with open(STUDENTS_CSV, 'r', newline='', encoding='utf-8') as f_read:
                     csv_headers = next(csv.reader(f_read))
                     if all(h in csv_headers for h in STUDENT_HEADERS): headers = csv_headers
            # Write all students (including the updated one)
            with open(STUDENTS_CSV, mode='w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=headers, extrasaction='ignore')
                writer.writeheader()
                writer.writerows(all_students)
            flash(f"Student '{updated_data['firstName']}' updated successfully!", 'success')
            print(f"Rewrote {STUDENTS_CSV} successfully after update.") # Debug print
        except Exception as e:
            flash(f"Error rewriting {STUDENTS_CSV}: {e}", 'error')
            print(f"Error rewriting {STUDENTS_CSV}: {e}"); traceback.print_exc()
            # !! Consider rolling back in-memory change if CSV write fails !!
            # student_profile_data[student_id] = original_student # Example rollback

        return redirect(url_for('manage_students')) # Redirect back to the list

    except Exception as e:
        flash(f"An error occurred during update: {e}", 'error')
        print(f"Error during update_student for {student_id}: {e}"); traceback.print_exc()
        return redirect(url_for('edit_student', student_id=student_id)) # Redirect back to edit form

# --- UPDATED: MY COURSES Route ---
@app.route('/my_courses')
@no_cache
def my_courses():
    if not check_student_auth(): return redirect(url_for('index'))
    student_id = session['user_id']
    grades = student_grades_data.get(student_id, [])
    attendance = student_attendance_data.get(student_id, [])

    # --- Analytics ---
    student_courses = set() # Track all unique course names for this student
    course_progress = {}    # Track grade progress {courseName: {total: x, count: y}}

    # 1. Get course names and calculate progress from grades
    for g in grades:
        name, score_str = g.get('courseName'), g.get('score')
        if name: student_courses.add(name) # Add course name
        if name and score_str is not None:
            if name not in course_progress: course_progress[name]={'total':0,'count':0}
            try: course_progress[name]['total']+=float(score_str); course_progress[name]['count']+=1
            except (ValueError, TypeError): continue

    # 2. Get course names from attendance (in case no grades exist yet)
    for att in attendance:
        name = att.get('courseName')
        if name: student_courses.add(name)

    # 3. Build the final list, getting instructor primarily from main course_data
    course_list = []
    for name in sorted(list(student_courses)):
        # Calculate progress
        progress_data = course_progress.get(name, {'count': 0})
        prog = int(round((progress_data.get('total',0)/(progress_data.get('count',1) or 1)),0)) # Avoid div by zero

        # Find instructor - PRIORITIZE courses.csv data
        instructor_name = "N/A"
        found_in_main_data = False
        for code, details in course_data.items():
            if isinstance(details, dict) and details.get('courseName') == name:
                instructor_name = details.get('instructor', 'N/A') # Get official instructor name
                found_in_main_data = True
                break

        # Fallback: If not in courses.csv, try finding from student's attendance log (less reliable)
        if not found_in_main_data:
            for att in attendance:
                 if att.get('courseName') == name and att.get('instructor'):
                     instructor_name = att.get('instructor')
                     break # Take the first one found

        course_list.append({
            'name': name,
            'progress': prog,
            'instructor': instructor_name
        })
    # --- END Analytics ---

    return render_template('my_courses.html', user_name=session.get('name','?'), course_list=course_list)

@app.route('/grades')
def grades():
    if not check_student_auth():
        return redirect(url_for('index'))

    student_id = session['user_id']
    profile = student_profile_data.get(student_id, {})
    grades = student_grades_data.get(student_id, [])

    # --- ANALYTICS ---
    gpa = profile.get('gpa', 'N/A') # Get from profile
    total_score = 0
    highest_grade = {'score': 0, 'name': 'N/A'}
    lowest_grade = {'score': 101, 'name': 'N/A'} # Use 101 to ensure first valid score becomes lowest
    valid_grade_count = 0

    if grades:
        for g in grades:
            try:
                score_str = g.get('score')
                if score_str is None:
                    continue
                score = float(score_str)
                total_score += score
                valid_grade_count += 1

                course_name = g.get('courseName', 'Unknown Course')
                assignment_name = g.get('assignmentName', 'Unknown Assignment')
                grade_name = f"{course_name} - {assignment_name}"

                if score > highest_grade['score']:
                    highest_grade['score'] = score
                    highest_grade['name'] = grade_name
                if score < lowest_grade['score']:
                    lowest_grade['score'] = score
                    lowest_grade['name'] = grade_name
            except (ValueError, TypeError):
                print(f"Warning: Skipping grade due to invalid score format in grades for student {student_id}: {g}")
                continue

    # Avoid division by zero if no valid grades found
    overall_grade = (total_score / valid_grade_count) if valid_grade_count > 0 else 0
    # Adjust lowest score display if no grades were processed
    if lowest_grade['score'] > 100:
        lowest_grade['score'] = 'N/A'
    # --- END ANALYTICS ---

    return render_template(
        'grades.html',
        user_name=session['name'],
        grades=grades,
        gpa=gpa,
        overall_grade=round(overall_grade, 2),
        highest_grade=highest_grade,
        lowest_grade=lowest_grade
    )
# (Keep all existing imports and setup)
# ...

# --- MODIFIED: manage_courses route ---
@app.route('/manage_courses')
def manage_courses():
    if not check_faculty_auth(): return redirect(url_for('index'))
    faculty_id = session.get('user_id') # Get current faculty ID

    course_list_display = []
    processed_course_names = set() # Track names added from course_data

    # 1. Prioritize data from courses.csv (course_data)
    for code, details in course_data.items():
        if isinstance(details, dict) and details.get('courseName'):
            course_name = details['courseName']
            processed_course_names.add(course_name)
            # Count students associated with this specific course name
            student_count = 0
            student_ids = set()
            for sid, g_list in student_grades_data.items():
                for g in g_list:
                    if g.get('courseName') == course_name: student_ids.add(sid)
            for sid, a_list in student_attendance_data.items():
                for a in a_list:
                    if a.get('courseName') == course_name: student_ids.add(sid)
            student_count = len(student_ids)

            course_list_display.append({
                'code': code, # Pass the code for editing
                'name': course_name,
                'student_count': student_count,
                'semester': details.get('semester', 'N/A'), # Get semester if available
                'facultyId': details.get('facultyId', None) # Pass facultyId
            })

    # 2. Add courses inferred only from grades/attendance (if any)
    inferred_course_names = set()
    for _, g_list in student_grades_data.items(): [inferred_course_names.add(g['courseName']) for g in g_list if g.get('courseName')]
    for _, a_list in student_attendance_data.items(): [inferred_course_names.add(a['courseName']) for a in a_list if a.get('courseName')]

    for name in inferred_course_names:
        if name not in processed_course_names: # Only add if not already added from course_data
            student_ids = set()
            for sid, g_list in student_grades_data.items():
                for g in g_list:
                    if g.get('courseName') == name: student_ids.add(sid)
            for sid, a_list in student_attendance_data.items():
                for a in a_list:
                    if a.get('courseName') == name: student_ids.add(sid)

            course_list_display.append({
                'code': None, # No code available for inferred courses
                'name': name,
                'student_count': len(student_ids),
                'semester': 'N/A',
                'facultyId': None
            })

    # Sort the final list by name
    course_list_display_sorted = sorted(course_list_display, key=lambda x: x['name'])

    return render_template(
        'manage_courses.html',
        user_name=session.get('name', '?'),
        course_list=course_list_display_sorted,
        current_faculty_id=faculty_id # Pass current faculty ID for potential auth display
    )


# --- NEW ROUTE: Display Edit Course Form ---
@app.route('/edit_course/<course_code>')
def edit_course(course_code):
    if not check_faculty_auth(): return redirect(url_for('index'))

    course_details = course_data.get(course_code)
    if not course_details or not isinstance(course_details, dict):
        flash(f"Course with code '{course_code}' not found.", 'error')
        return redirect(url_for('manage_courses'))

    # Authorization Check (Optional but recommended): Allow only assigned faculty or specific admins to edit
    # current_faculty_id = session.get('user_id')
    # assigned_faculty_id = course_details.get('facultyId')
    # if assigned_faculty_id != current_faculty_id and current_faculty_id != 'admin_user': # Example admin check
    #      flash(f"You are not authorized to edit course {course_code}.", 'error')
    #      return redirect(url_for('manage_courses'))

    # Get faculty list for dropdown
    faculty_list = [{"id": f_id, "name": f_info['name']} for f_id, f_info in faculty_users.items() if f_info['role'] == 'faculty']

    return render_template(
        'edit_course.html',
        user_name=session.get('name', '?'),
        course=course_details, # Pass current course data
        faculty_list=faculty_list # Pass list for faculty dropdown
    )


# --- NEW ROUTE: Handle Update Course Form Submission ---
@app.route('/update_course/<course_code>', methods=['POST'])
def update_course(course_code):
    if not check_faculty_auth(): return redirect(url_for('index'))

    original_course = course_data.get(course_code)
    if not original_course or not isinstance(original_course, dict):
        flash(f"Course '{course_code}' not found for update.", 'error')
        return redirect(url_for('manage_courses'))

    # Authorization Check (Repeat check on POST)
    # current_faculty_id = session.get('user_id')
    # assigned_faculty_id = original_course.get('facultyId')
    # if assigned_faculty_id != current_faculty_id and current_faculty_id != 'admin_user':
    #      flash(f"Unauthorized edit attempt for course {course_code}.", 'error')
    #      return redirect(url_for('manage_courses'))

    try:
        # 1. Get updated form data
        updated_data = {
            'courseCode': course_code, # Keep original code
            'courseName': request.form.get('courseName','').strip(),
            'description': request.form.get('courseDescription', '').strip(),
            'instructor': request.form.get('instructor', '').strip(),
            'semester': request.form.get('semester', '').strip(),
            'credits': request.form.get('credits', '').strip(),
            'facultyId': request.form.get('facultyId', '').strip() # Get assigned faculty
        }

        # 2. Basic Validation
        required = ['courseName', 'instructor', 'semester', 'credits', 'facultyId']
        if not all(updated_data.get(f) for f in required):
            flash('Required fields cannot be empty.', 'error')
            # Re-render edit form with errors? Or just redirect back with flash.
            return redirect(url_for('edit_course', course_code=course_code)) # Redirect back to edit

        # Validate credits is a number
        try: updated_data['credits'] = int(updated_data['credits'])
        except ValueError: flash('Credits must be a number.', 'error'); return redirect(url_for('edit_course', course_code=course_code))

        # Validate facultyId exists
        if updated_data['facultyId'] not in faculty_users:
            flash(f"Invalid Faculty ID '{updated_data['facultyId']}'.", 'error'); return redirect(url_for('edit_course', course_code=course_code))

        # 3. Update in-memory dictionary
        course_data[course_code] = updated_data
        print(f"Updated course data in memory for {course_code}: {updated_data}")

        # 4. Rewrite the entire courses.csv file
        all_courses = list(course_data.values())
        headers = COURSE_HEADERS # Use defined headers
        try:
            with open(COURSES_CSV, mode='w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=headers, extrasaction='ignore')
                writer.writeheader()
                writer.writerows(all_courses) # Write all courses (including the updated one)
            flash(f"Course '{updated_data['courseName']}' updated successfully!", 'success')
            print(f"Rewrote {COURSES_CSV} successfully.")
        except Exception as e:
            flash(f"Error rewriting {COURSES_CSV}: {e}", 'error')
            print(f"Error rewriting {COURSES_CSV}: {e}"); traceback.print_exc()
            # !! Consider rolling back the in-memory change if CSV write fails !!
            # course_data[course_code] = original_course # Example rollback

        return redirect(url_for('manage_courses'))

    except Exception as e:
        flash(f"An error occurred during update: {e}", 'error')
        print(f"Error during update_course for {course_code}: {e}"); traceback.print_exc()
        return redirect(url_for('edit_course', course_code=course_code)) # Redirect back to edit form on error


# (Keep all other existing routes: faculty_dashboard, uploads, student routes, attendance, reports, etc.)
# ...
@app.route('/attendance')
@no_cache
def attendance():
    if not check_student_auth():
        return redirect(url_for('index'))

    student_id = session['user_id']
    attendance_log = student_attendance_data.get(student_id, [])

    # --- ANALYTICS ---
    total_classes = len(attendance_log)
    present_count = 0
    absent_count = 0
    late_count = 0
    by_subject = {}

    for record in attendance_log:
        status = record.get('status')
        subject = record.get('courseName')

        # Skip if subject or status is missing
        if not subject or not status:
            print(f"Warning: Skipping attendance record due to missing subject or status for student {student_id}: {record}")
            continue

        if subject not in by_subject:
            by_subject[subject] = {'present': 0, 'total': 0}

        by_subject[subject]['total'] += 1

        if status == 'Present':
            present_count += 1
            by_subject[subject]['present'] += 1
        elif status == 'Absent':
            absent_count += 1
        elif status == 'Late':
            late_count += 1
            by_subject[subject]['present'] += 1 # Late still counts as attended

    # Avoid division by zero
    overall_perc = (present_count / total_classes) * 100 if total_classes > 0 else 0

    subject_summary = []
    for subject, data in by_subject.items():
        perc = (data['present'] / data['total']) * 100 if data['total'] > 0 else 0
        subject_summary.append({
            'name': subject,
            'percentage': round(perc),
            'attended': data['present'],
            'total': data['total']
        })
    # --- END ANALYTICS ---

    # Sort daily log safely, handling missing dates
    safe_log_for_sort = [log for log in attendance_log if log.get('date')]
    sorted_log = sorted(safe_log_for_sort, key=lambda x: x['date'], reverse=True)


    return render_template(
        'attendance.html',
        user_name=session['name'],
        overall_perc=round(overall_perc),
        present_count=present_count,
        absent_count=absent_count,
        late_count=late_count,
        total_classes=total_classes,
        subject_summary=subject_summary,
        daily_log=sorted_log # Show recent first
    )

@app.route('/profile')
@no_cache
def profile():
    if not check_student_auth():
        return redirect(url_for('index'))

    student_id = session['user_id']
    profile = student_profile_data.get(student_id, {})

    return render_template(
        'profile.html',
        user_name=session['name'],
        user=profile
    )

# =================================================================
# 6. SERVER ROUTES - FACULTY (Data Upload & Management)
# =================================================================

def check_faculty_auth():
    """Helper to check if a user is a logged-in faculty member."""
    return session.get('role') == 'faculty'

def is_faculty_authorized_for_course(faculty_id, course_name):
    """
    Determine whether the given faculty_id is authorized to manage the specified course_name.

    Logic:
    - If a course entry exists in course_data with a matching courseName and it has a facultyId,
      require that facultyId == faculty_id.
    - If a course entry exists but has no facultyId assigned, allow the action.
    - If no course entry is found (course inferred from grades/attendance), allow by default
      so courses not present in course_data (inferred courses) can still be managed.
    - Return False if faculty_id or course_name is missing.
    """
    if not faculty_id or not course_name:
        return False

    # Normalize course_name for exact comparison (caller should provide consistent names)
    for code, details in course_data.items():
        if isinstance(details, dict):
            cn = details.get('courseName')
            if cn and cn == course_name:
                assigned = details.get('facultyId')
                if assigned:
                    return assigned == faculty_id
                # If course exists but no faculty assigned, allow by default
                return True

    # If no matching course found in course_data (inferred course), allow by default
    return True

@app.route('/faculty_dashboard')
@no_cache
def faculty_dashboard():
    if not check_faculty_auth(): return redirect(url_for('index'))
    total_students = len(student_profile_data)
    total_score, total_grades, subject_perf = 0, 0, {}
    # NEW: Dictionary to hold grade counts
    grade_distribution = {'A': 0, 'B': 0, 'C': 0, 'D/F': 0}

    for _, grades_list in student_grades_data.items():
        for g in grades_list:
            try:
                score_str, subject = g.get('score'), g.get('courseName')
                if score_str is None or not subject: continue
                score = float(score_str)
                total_score += score; total_grades += 1

                # Subject Performance calculation (existing)
                if subject not in subject_perf: subject_perf[subject] = {'total': 0, 'count': 0}
                subject_perf[subject]['total'] += score; subject_perf[subject]['count'] += 1

                # NEW: Grade Distribution calculation
                if score >= 90: grade_distribution['A'] += 1
                elif score >= 80: grade_distribution['B'] += 1
                elif score >= 70: grade_distribution['C'] += 1
                else: grade_distribution['D/F'] += 1

            except (ValueError, TypeError): continue

    class_avg = round((total_score / total_grades), 2) if total_grades > 0 else 0
    top_subj, top_avg = "N/A", 0
    chart_labels = list(subject_perf.keys()); chart_scores = []
    for subj in chart_labels:
        avg = round((subject_perf[subj]['total'] / subject_perf[subj]['count']), 2) if subject_perf[subj]['count'] > 0 else 0
        chart_scores.append(avg);
        if avg > top_avg: top_avg, top_subj = avg, subj # Find max average

    # NEW: Prepare grade distribution data for the chart
    dist_labels = list(grade_distribution.keys())
    dist_values = list(grade_distribution.values())

    return render_template(
        'faculty_dashboard.html',
        user_name=session.get('name', '?'),
        total_students=total_students,
        class_average=class_avg,
        top_subject=top_subj,
        top_subject_avg=top_avg,
        chart_labels=json.dumps(chart_labels),  # For radar chart
        chart_scores=json.dumps(chart_scores),  # For radar chart
        dist_labels=json.dumps(dist_labels),    # NEW: For pie chart
        dist_values=json.dumps(dist_values)     # NEW: For pie chart
    )
# --- ADD THESE TWO NEW ROUTES ---
# --- NEW ROUTE: Faculty Profile ---
@app.route('/faculty_profile')
def faculty_profile():
    if not check_faculty_auth():
        return redirect(url_for('index'))

    faculty_id = session.get('user_id')
    faculty_info = faculty_users.get(faculty_id) # Get info from the dictionary

    # Add the faculty ID to the info dictionary for display
    if faculty_info:
        faculty_info_display = faculty_info.copy() # Avoid modifying original dict
        faculty_info_display['id'] = faculty_id
    else:
        faculty_info_display = None # Handle case where info might be missing

    return render_template(
        'faculty_profile.html',
        user_name=session.get('name', '?'),
        faculty_info=faculty_info_display
        )
# --- END NEW ROUTE ---
# --- NEW ROUTE: Course Details for Student ---
@app.route('/course_details/<course_name>')
def course_details(course_name):
    if not check_student_auth(): return redirect(url_for('index'))
    student_id = session['user_id']
    safe_course_name = course_name.replace('+', ' ') # Decode course name from URL

    # 1. Filter grades for this student and this course
    all_grades = student_grades_data.get(student_id, [])
    course_grades = [g for g in all_grades if g.get('courseName') == safe_course_name]

    # 2. Filter attendance for this student and this course
    all_attendance = student_attendance_data.get(student_id, [])
    course_attendance = [a for a in all_attendance if a.get('courseName') == safe_course_name]

    # 3. Calculate stats specific to this course
    total_score, count_g = 0, 0
    for g in course_grades:
        try: score_str = g.get('score'); total_score += float(score_str or 0); count_g += 1 if score_str is not None else 0
        except (ValueError, TypeError): pass
    course_average = round((total_score / count_g), 2) if count_g > 0 else None # Use None if no grades

    total_c = len(course_attendance); present = sum(1 for a in course_attendance if a.get('status') in ['Present','Late'])
    course_attendance_perc = int(round((present / total_c) * 100, 0)) if total_c > 0 else None # Use None if no attendance

    # 4. Find Instructor (look in attendance first, then course_data)
    instructor = "N/A"
    for att in course_attendance:
        if att.get('instructor'): instructor = att['instructor']; break
    if instructor == "N/A": # Fallback to course_data
         for _, c_info in course_data.items():
             if isinstance(c_info, dict) and c_info.get('courseName') == safe_course_name and c_info.get('instructor'):
                 instructor = c_info['instructor']; break

    # Sort grades and attendance by date
    sorted_grades = sorted([g for g in course_grades if g.get('dateGraded')], key=lambda x:x['dateGraded'], reverse=True)
    sorted_attendance = sorted([a for a in course_attendance if a.get('date')], key=lambda x:x['date'], reverse=True)


    return render_template('course_details.html',
                           user_name=session.get('name', '?'),
                           course_name=safe_course_name,
                           course_grades=sorted_grades,
                           course_attendance=sorted_attendance,
                           course_average=course_average,
                           course_attendance_perc=course_attendance_perc,
                           instructor=instructor
                           )
# --- END NEW ROUTE ---
@app.route('/student_dashboard')
@no_cache
def student_dashboard():
    if not check_student_auth(): return redirect(url_for('index'))
    student_id = session['user_id']
    profile = student_profile_data.get(student_id, {})
    grades = student_grades_data.get(student_id, [])
    # NEW: Get attendance log for calculations
    attendance_log = student_attendance_data.get(student_id, [])

    # --- Grade Analytics (Existing) ---
    total_score, subjects, valid_grade_count = 0, {}, 0
    safe_grades = sorted([g for g in grades if g.get('dateGraded')], key=lambda x: x['dateGraded'], reverse=True)
    recent_grades = safe_grades[:3]
    for g in grades:
        try:
            score_str, subj = g.get('score'), g.get('courseName', '?');
            if score_str is None or not subj: continue
            score = float(score_str); total_score += score; valid_grade_count += 1
            if subj not in subjects: subjects[subj] = {'total': 0, 'count': 0}
            subjects[subj]['total'] += score; subjects[subj]['count'] += 1
        except (ValueError, TypeError): continue
    overall_grade = round((total_score / valid_grade_count), 2) if valid_grade_count > 0 else 0
    labels = list(subjects.keys()); scores = [round((subjects[s]['total']/subjects[s]['count']),2) if subjects[s]['count']>0 else 0 for s in labels]

    # --- NEW: Attendance Analytics ---
    total_classes = len(attendance_log)
    present_count = sum(1 for a in attendance_log if a.get('status') in ['Present','Late'])
    overall_attendance_perc = int(round((present_count / total_classes) * 100, 0)) if total_classes > 0 else 0 # Calculate percentage

    # Determine attendance description (optional)
    attendance_desc = "Excellent" if overall_attendance_perc >= 90 else "Good" if overall_attendance_perc >= 80 else "Needs Improvement" if overall_attendance_perc >= 70 else "Poor" if total_classes > 0 else "N/A"
    # --- END NEW ---


    return render_template('student_dashboard.html',
                           user_name=session.get('name', '?'),
                           profile=profile,
                           overall_grade=overall_grade,
                           recent_grades=recent_grades,
                           chart_labels=json.dumps(labels),
                           chart_scores=json.dumps(scores),
                           # NEW: Pass attendance data
                           overall_attendance=overall_attendance_perc,
                           attendance_description=attendance_desc
                           )

@app.route('/student_attendance_log/<student_id>')
def student_attendance_log(student_id):
    """Displays the full attendance log for a specific student."""
    if not check_faculty_auth(): return redirect(url_for('index'))
    profile = student_profile_data.get(student_id)
    if not profile:
        flash(f"Student '{student_id}' not found.",'error')
        return redirect(url_for('manage_students'))

    attendance_log = student_attendance_data.get(student_id, [])
    # Sort attendance log by date for display
    sorted_log = sorted([l for l in attendance_log if l.get('date')], key=lambda x:x['date'], reverse=True)

    return render_template('student_attendance_log.html',
                           user_name=session.get('name', '?'),
                           student=profile,
                           attendance=sorted_log)

# --- END OF NEW ROUTES ---
@app.route('/upload_data')
@no_cache
def upload_data():
    if not check_faculty_auth():
        return redirect(url_for('index'))
    return render_template('upload_data.html', user_name=session['name'])
# --- ADD THIS COMPLETE FUNCTION ---
@app.route('/view_student/<student_id>')
@no_cache
def view_student(student_id):
    if not check_faculty_auth(): return redirect(url_for('index'))
    profile = student_profile_data.get(student_id)
    if not profile:
        flash(f"Student '{student_id}' not found.",'error')
        return redirect(url_for('manage_students'))

    grades = student_grades_data.get(student_id,[])
    att_log = student_attendance_data.get(student_id,[])
    total_s, count_g = 0,0
    for g in grades:
        try:
            score_str=g.get('score')
            total_s+=float(score_str or 0)
            count_g+=1 if score_str is not None else 0
        except (ValueError, TypeError): pass # Skip invalid scores
    overall_g=round((total_s/count_g),2) if count_g>0 else 0

    total_c=len(att_log)
    present=sum(1 for a in att_log if a.get('status') in ['Present','Late'])
    overall_a=round((present/total_c)*100,0) if total_c>0 else 0

    # Sort grades and attendance safely
    sorted_g = sorted([g for g in grades if g.get('dateGraded')], key=lambda x:x['dateGraded'], reverse=True)
    sorted_l = sorted([l for l in att_log if l.get('date')], key=lambda x:x['date'], reverse=True)

    return render_template('view_student.html',
                           user_name=session.get('name', '?'),
                           student=profile,
                           grades=sorted_g,
                           attendance=sorted_l,
                           overall_grade=overall_g,
                           overall_attendance=int(overall_a))
# --- END OF ADDED FUNCTION ---

# --- Keep the existing delete_student route definition ---
@app.route('/delete_student/<student_id>', methods=['POST'])
@no_cache
def delete_student(student_id):
    # Delete a student from in-memory stores and attempt to persist changes to students.csv
    if not check_faculty_auth():
        return redirect(url_for('index'))

    name = "Unknown"
    profile = student_profile_data.pop(student_id, None)
    if profile:
        name = f"{profile.get('firstName','')} {profile.get('lastName','')}".strip()

    # Remove from other in-memory dictionaries
    student_login_data.pop(student_id, None)
    student_grades_data.pop(student_id, None)
    student_attendance_data.pop(student_id, None)

    csv_path = 'students.csv'
    if os.path.isfile(csv_path):
        students = list(student_profile_data.values())
        headers = ['studentId', 'password', 'firstName', 'lastName', 'email', 'major', 'program', 'gpa', 'enrollmentDate', 'dob']  # Default headers
        try:
            # Use existing headers if they are valid
            if os.path.getsize(csv_path) > 0:
                with open(csv_path, 'r', newline='', encoding='utf-8') as f_read:
                    csv_headers = next(csv.reader(f_read))
                    if all(h in csv_headers for h in headers):
                        headers = csv_headers

            # Write updated student list
            with open(csv_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=headers, extrasaction='ignore')
                writer.writeheader()
                writer.writerows(students)

            flash(f"Student '{name}' deleted.", 'success')
        except Exception as e:
            flash(f"Error rewriting students.csv: {e}", 'error')
            print(traceback.format_exc())
    else:
        flash(f"Student '{name}' removed from memory; students.csv not found.", 'warning')

    return redirect(url_for('manage_students'))

# ... (rest of your app.py code) ...
@app.route('/upload-student-data', methods=['POST'])
@no_cache
def upload_student_data():
    if not check_faculty_auth():
        return "Unauthorized", 403

    file = request.files.get('student-data-csv')
    if not file or file.filename == '':
        flash('No selected file for student data', 'error')
        return redirect(url_for('upload_data'))

    if file and file.filename.endswith('.csv'):
        # Ensure filename is secure
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        try:
            file.save(filepath)

            # Load profile data
            load_data_from_csv(filepath, student_profile_data, 'studentId', is_list=False)

            # Also populate login data from the same file
            student_login_data.clear()
            for student_id, profile in student_profile_data.items():
                if 'password' in profile:
                    student_login_data[student_id] = {
                        "password": profile['password'],
                        "role": "student"
                    }
                else:
                    print(f"Warning: No password found for student {student_id} in uploaded file.")

            os.remove(filepath) # Clean up uploaded file
            flash('Student data uploaded successfully!', 'success')
        except Exception as e:
            flash(f"Error processing student data file: {e}", 'error')
            # Clean up potentially corrupted file if save succeeded but processing failed
            if os.path.exists(filepath):
                 os.remove(filepath)
    else:
        flash('Invalid file type for student data. Please upload a .csv file.', 'error')

    return redirect(url_for('upload_data'))

@app.route('/upload-grades-data', methods=['POST'])
@no_cache
def upload_grades_data():
    if not check_faculty_auth():
        return "Unauthorized", 403

    file = request.files.get('grades-data-csv')
    if not file or file.filename == '':
        flash('No selected file for grades data', 'error')
        return redirect(url_for('upload_data'))

    if file and file.filename.endswith('.csv'):
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        try:
            file.save(filepath)
            load_data_from_csv(filepath, student_grades_data, 'studentId', is_list=True)
            os.remove(filepath)
            flash('Grades data uploaded successfully!', 'success')
        except Exception as e:
             flash(f"Error processing grades data file: {e}", 'error')
             if os.path.exists(filepath):
                 os.remove(filepath)
    else:
        flash('Invalid file type for grades data. Please upload a .csv file.', 'error')

    return redirect(url_for('upload_data'))

@app.route('/upload-attendance-data', methods=['POST'])
@no_cache
def upload_attendance_data():
    if not check_faculty_auth():
        return "Unauthorized", 403

    file = request.files.get('attendance-data-csv')
    if not file or file.filename == '':
        flash('No selected file for attendance data', 'error')
        return redirect(url_for('upload_data'))

    if file and file.filename.endswith('.csv'):
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        try:
            file.save(filepath)
            load_data_from_csv(filepath, student_attendance_data, 'studentId', is_list=True)
            os.remove(filepath)
            flash('Attendance data uploaded successfully!', 'success')
        except Exception as e:
             flash(f"Error processing attendance data file: {e}", 'error')
             if os.path.exists(filepath):
                 os.remove(filepath)
    else:
        flash('Invalid file type for attendance data. Please upload a .csv file.', 'error')

    return redirect(url_for('upload_data'))


@app.route('/manage_students')
@no_cache
def manage_students():
    if not check_faculty_auth():
        return redirect(url_for('index'))

    # Create a list of students with their analytics
    student_list = []
    for student_id, profile in student_profile_data.items():
        # Get grades
        grades = student_grades_data.get(student_id, [])
        total_score = 0
        valid_grade_count = 0
        for g in grades:
            try:
                score_str = g.get('score')
                if score_str is not None:
                    total_score += float(score_str)
                    valid_grade_count += 1
            except (ValueError, TypeError):
                 print(f"Warning: Skipping grade due to invalid score in manage_students for {student_id}: {g}")
                 continue
        # Avoid division by zero
        overall_grade = (total_score / valid_grade_count) if valid_grade_count > 0 else 0

        # Get attendance
        attendance = student_attendance_data.get(student_id, [])
        present = 0
        for a in attendance:
            # Only count valid statuses
            status = a.get('status')
            if status in ['Present', 'Late']:
                present += 1
        # Avoid division by zero
        overall_attendance = (present / len(attendance)) * 100 if attendance else 0

        student_list.append({
            'id': student_id,
            'name': f"{profile.get('firstName', '')} {profile.get('lastName', '')}".strip(),
            'grade': round(overall_grade, 2),
            'attendance': round(overall_attendance)
        })

    return render_template(
        'manage_students.html',
        user_name=session['name'],
        students=student_list
    )

# --- API ROUTE FOR ROSTER ---
@app.route('/api/get_roster/<course_name>')
@no_cache
def get_roster_api(course_name):
    if not check_faculty_auth():
        return jsonify({"error": "Unauthorized"}), 403

    # Decode URL-encoded course name
    safe_course_name = course_name.replace('+', ' ')

    student_ids_in_course = set()
    # Find students from both grades and attendance records
    for student_id, grades in student_grades_data.items():
        for grade in grades:
            if grade.get('courseName') == safe_course_name:
                student_ids_in_course.add(student_id)
    for student_id, attendance_list in student_attendance_data.items():
        for attendance in attendance_list:
            if attendance.get('courseName') == safe_course_name:
                student_ids_in_course.add(student_id)

    roster = []
    for student_id in sorted(list(student_ids_in_course)):
        profile = student_profile_data.get(student_id)
        if profile:
            roster.append({
                'id': student_id,
                'name': f"{profile.get('firstName', 'N/A')} {profile.get('lastName', 'N/A')}"
            })

    return jsonify(roster)

# --- SUBMIT ROUTE FOR ATTENDANCE ---
@app.route('/submit_attendance', methods=['POST'])
@no_cache
def submit_attendance():
    if not check_faculty_auth():
        return redirect(url_for('index'))

    try:
        course_name = request.form.get('course')
        attendance_date = request.form.get('date')

        # Basic validation
        if not course_name or not attendance_date:
             flash('Missing course name or date.', 'error')
             return redirect(url_for('take_attendance'))

        # Find the instructor name (can be improved if instructor data is more structured)
        instructor_name = "N/A"
        found_instructor = False
        for _ , attendance_list in student_attendance_data.items():
            for att in attendance_list:
                if att.get('courseName') == course_name and att.get('instructor'):
                    instructor_name = att.get('instructor')
                    found_instructor = True
                    break
            if found_instructor:
                break

        new_records = []
        # Loop through all form items to find the attendance data
        # Assume roster was loaded, so iterate through expected students
        # This requires knowing which students *should* have been in the form
        submitted_student_ids = {key.replace('attendance_', '') for key in request.form if key.startswith('attendance_')}

        for student_id in submitted_student_ids:
             status = request.form.get(f'attendance_{student_id}')
             if status: # Ensure a status was selected
                 new_record = {
                     'studentId': student_id,
                     'courseName': course_name,
                     'date': attendance_date,
                     'status': status,
                     'instructor': instructor_name
                 }
                 new_records.append(new_record)
             else:
                 print(f"Warning: No status submitted for student {student_id} in course {course_name}")


        if not new_records:
             flash('No attendance data submitted.', 'warning')
             return redirect(url_for('take_attendance'))

        # --- 1. Append to CSV file for persistence ---
        csv_file = 'attendance.csv'
        file_exists = os.path.isfile(csv_file)

        # Determine headers dynamically or use a fixed set
        headers = ['studentId', 'courseName', 'date', 'status', 'instructor']
        # Check if file exists and has content to decide on writing headers
        write_header = not file_exists or os.path.getsize(csv_file) == 0

        with open(csv_file, mode='a', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=headers, extrasaction='ignore') # Ignore extra fields if any

            if write_header:
                 writer.writeheader()

            writer.writerows(new_records) # Use writerows for efficiency

        # --- 2. Update in-memory dictionary ---
        for record in new_records:
            student_id = record['studentId']
            if student_id not in student_attendance_data:
                student_attendance_data[student_id] = []
            # Avoid adding duplicates if submitting for the same day/course again
            # Simple check:
            is_duplicate = any(
                r['courseName'] == record['courseName'] and r['date'] == record['date']
                for r in student_attendance_data[student_id]
            )
            if not is_duplicate:
                student_attendance_data[student_id].append(record)
            else:
                 print(f"Note: Duplicate attendance record skipped for {student_id} on {attendance_date} for {course_name}")


        flash(f"Attendance for {course_name} on {attendance_date} submitted successfully!", 'success')

    except Exception as e:
        print(f"Error submitting attendance: {e}")
        flash(f"An error occurred while submitting attendance: {e}", 'error')

    return redirect(url_for('take_attendance'))


# =================================================================
# 7. SERVER ROUTES - FACULTY (STATIC & DYNAMIC PAGES)
# =================================================================


# --- ROUTE TO CREATE STUDENT ---
@app.route('/create_student', methods=['POST'])
@no_cache
def create_student():
    if not check_faculty_auth(): return redirect(url_for('index')) # Check if logged-in user is faculty
    try:
        # 1. Get data submitted from the HTML form
        data = request.form
        # Define required fields (excluding optional/default ones like major, program, gpa)
        req = STUDENT_HEADERS[:-3] + ['confirmPassword'] # dob is also required based on the list comprehension below

        # 2. Basic Validation: Check if all required fields were filled
        # Note: Excludes major, program, gpa which have defaults
        if not all(data.get(f,"").strip() for f in req if f not in ['major','program','gpa']):
            flash('Required fields missing or empty.', 'error')
            return redirect(url_for('add_student')) # Go back to the form

        # Check if passwords match
        if data['password'] != data['confirmPassword']:
             flash('Passwords mismatch.', 'error')
             return redirect(url_for('add_student')) # Go back to the form

        # 3. Get Student ID and check for duplicates
        sid = data['studentId'].strip() # Remove leading/trailing spaces
        if not sid: # Check if ID is empty after stripping
             flash('Student ID cannot be empty.', 'error')
             return redirect(url_for('add_student'))
        if sid in student_profile_data: # Check if ID already exists in our data
            flash(f"ID '{sid}' already exists.", 'error')
            return redirect(url_for('add_student'))

        # 4. Prepare the new student record using standard headers
        # It takes values from the form `data` or defaults to '' if not found
        record = {h: data.get(h,'') for h in STUDENT_HEADERS}
        # Explicitly set default values for fields not necessarily in the form
        record['major'] = data.get('major') or 'Undeclared'
        record['program'] = data.get('program') or 'Undeclared'
        record['gpa'] = data.get('gpa') or '0.0'

        # 5. Append the new student record to the students.csv file
        exists = os.path.isfile(STUDENTS_CSV); headers = STUDENT_HEADERS; existing_h = headers
        # Check if file exists and isn't empty to decide on headers
        if exists and os.path.getsize(STUDENTS_CSV)>0:
            try:
                # Read existing headers to maintain consistency
                with open(STUDENTS_CSV,'r',newline='',encoding='utf-8') as f: existing_h = next(csv.reader(f))
                # Use existing headers only if they contain all default headers
                if not all(h in existing_h for h in headers):
                    print(f"Warning: {STUDENTS_CSV} headers mismatch. Using default headers.")
                    existing_h=headers
            except StopIteration: pass # File was empty or just had header previously
        write_h = not exists or os.path.getsize(STUDENTS_CSV)==0 # Decide if header needs writing
        with open(STUDENTS_CSV,'a',newline='',encoding='utf-8') as f:
            # Create a CSV writer using the determined headers
            # extrasaction='ignore' prevents errors if `record` has fewer keys than `existing_h`
            w = csv.DictWriter(f, fieldnames=existing_h, extrasaction='ignore')
            if write_h: w.writeheader() # Write header only if needed
            w.writerow(record) # Write the new student data row

        # 6. Update the in-memory dictionaries for immediate access
        student_profile_data[sid] = record # Add profile
        student_login_data[sid] = {'password':data['password'], 'role':'student'} # Add login info

        flash(f"Student '{data['firstName']}' added!",'success') # Success message
        return redirect(url_for('manage_students')) # Redirect to the student list

    except Exception as e: # Catch any unexpected errors during the process
        flash(f"Error creating student: {e}", 'error') # Show error message
        print(traceback.format_exc()) # Log the full error details to the console
        return redirect(url_for('add_student')) # Go back to the form on error
@app.route('/reports')
@no_cache
def reports():
    if not check_faculty_auth():
        return redirect(url_for('index'))

    # --- 1. Get Dynamic Course List for Dropdown ---
    course_names = set()
    for _ , grades in student_grades_data.items():
        for grade in grades:
             if grade.get('courseName'):
                course_names.add(grade['courseName'])
    for _ , attendance_list in student_attendance_data.items():
        for attendance in attendance_list:
             if attendance.get('courseName'):
                course_names.add(attendance['courseName'])
    sorted_courses = sorted([c for c in course_names if c])

    # --- 2. Analytics for Pass/Fail Chart ---
    course_stats = {}
    pass_threshold = 50  # Define what a "pass" is

    for _ , grades in student_grades_data.items():
        for grade in grades:
            try:
                course_name = grade.get('courseName')
                score_str = grade.get('score')

                if not course_name or score_str is None:
                    continue

                score = float(score_str)

                if course_name not in course_stats:
                    course_stats[course_name] = {'pass': 0, 'fail': 0}

                if score >= pass_threshold:
                    course_stats[course_name]['pass'] += 1
                else:
                    course_stats[course_name]['fail'] += 1
            except (ValueError, TypeError):
                 print(f"Warning: Skipping grade due to invalid score in reports: {grade}")
                 continue

    # Format data for Chart.js
    chart_labels = list(course_stats.keys())
    pass_data = [stats['pass'] for stats in course_stats.values()]
    fail_data = [stats['fail'] for stats in course_stats.values()]

    return render_template(
        'reports.html',
        user_name=session['name'],
        courses=sorted_courses,
        chart_labels=json.dumps(chart_labels),
        pass_data=json.dumps(pass_data),
        fail_data=json.dumps(fail_data)
    )

@app.route('/take_attendance')
@no_cache
def take_attendance():
    if not check_faculty_auth():
        return redirect(url_for('index'))

    # Get a unique list of all course names from our data
    course_names = set()
    for _ , grades in student_grades_data.items():
        for grade in grades:
            if grade.get('courseName'):
                 course_names.add(grade['courseName'])
    for _ , attendance_list in student_attendance_data.items():
        for attendance in attendance_list:
            if attendance.get('courseName'):
                course_names.add(attendance['courseName'])

    # Remove any None/empty values and sort the list
    sorted_courses = sorted([c for c in course_names if c])

    return render_template(
        'take_attendance.html',
        user_name=session['name'],
        courses=sorted_courses
    )

@app.route('/add_student')
@no_cache
def add_student():
    if not check_faculty_auth():
        return redirect(url_for('index'))
    return render_template('add_student.html', user_name=session['name'])


# --- ROUTE TO CREATE STUDENT ---



@app.route('/add_course')
@no_cache
def add_course():
    if not check_faculty_auth():
        return redirect(url_for('index'))
    # You might want to pass instructor list here if managing instructors separately
    return render_template('add_course.html', user_name=session['name'])

# Add a route to handle the actual creation of the course (similar to create_student)
# This would typically involve saving to a 'courses.csv' or database
@app.route('/create_course', methods=['POST'])
@no_cache
def create_course():
     if not check_faculty_auth():
         return redirect(url_for('index'))
     # 1. Get form data (courseName, courseCode, instructor, etc.)
     course_name = request.form.get('courseName')
     course_code = request.form.get('courseCode')
     # ... get other fields ...
     # 2. Add validation
     if not course_name or not course_code:
         flash("Course Name and Code are required.", "error")
         return redirect(url_for('add_course'))
     # 3. Save the data (e.g., append to a 'courses.csv')
     #    For simplicity, we'll just flash a success message here.
     #    In a real app, you would save this data persistently.
     print(f"Received course data: {request.form.to_dict()}")
     flash(f"Course '{course_name}' ({course_code}) added conceptually (not saved persistently).", "success")
     # 4. Redirect
     return redirect(url_for('manage_courses'))


# (Keep all existing imports and setup)
# ...

# --- MODIFIED: course_roster route ---
@app.route('/course_roster/<course_name>')
@no_cache
def course_roster(course_name):
    if not check_faculty_auth(): return redirect(url_for('index'))
    s_name = course_name.replace('+', ' ')
    faculty_id = session.get('user_id')

    # Optional stricter check: only assigned faculty sees roster
    # if not is_faculty_authorized_for_course(faculty_id, s_name):
    #    flash(f"Not authorized for roster {s_name}.", "error"); return redirect(url_for('manage_courses'))

    # Find students currently associated with the course
    ids_in_course = set()
    for sid, g_list in student_grades_data.items(): [ids_in_course.add(sid) for g in g_list if g.get('courseName') == s_name]
    for sid, a_list in student_attendance_data.items(): [ids_in_course.add(sid) for a in a_list if a.get('courseName') == s_name]

    # Build roster info for display
    roster_display = []
    for sid in sorted(list(ids_in_course)):
        profile = student_profile_data.get(sid)
        if profile: roster_display.append({'id':sid, 'name': f"{profile.get('firstName','?')} {profile.get('lastName','?')}", 'email': profile.get('email','?')})

    # --- NEW: Find students NOT in this course ---
    students_not_in_course = []
    all_student_ids = set(student_profile_data.keys())
    eligible_ids = all_student_ids - ids_in_course # Set difference

    for sid in sorted(list(eligible_ids)):
        profile = student_profile_data.get(sid)
        if profile:
            students_not_in_course.append({
                'id': sid,
                'name': f"{profile.get('firstName','?')} {profile.get('lastName','?')}"
            })
    # --- END NEW ---

    return render_template(
        'course_roster.html',
        user_name=session.get('name', '?'),
        course_name=s_name,
        roster=roster_display,
        available_students=students_not_in_course # Pass the new list
        )

# --- NEW ROUTE: Enroll Student (adds placeholder attendance) ---
@app.route('/enroll_student', methods=['POST'])
@no_cache
def enroll_student():
    if not check_faculty_auth(): return redirect(url_for('index'))
    faculty_id = session.get('user_id')
    faculty_name = session.get('name','?')

    try:
        course_name = request.form.get('course_name')
        student_id = request.form.get('student_id_to_add')

        # Basic Validation
        if not course_name or not student_id:
            flash("Missing course name or student ID.", "error")
            # Redirect back might be tricky without course_name in URL, maybe manage_courses?
            return redirect(request.referrer or url_for('manage_courses')) # Try redirecting back

        # Authorization Check (Faculty must teach the course)
        if not is_faculty_authorized_for_course(faculty_id, course_name):
            flash(f"You are not authorized to add students to {course_name}.", "error")
            return redirect(request.referrer or url_for('manage_courses'))

        # Check if student exists
        if student_id not in student_profile_data:
            flash(f"Student ID '{student_id}' does not exist.", "error")
            return redirect(request.referrer or url_for('course_roster', course_name=course_name.replace(' ','+')))

        # Check if student already has ANY record for this course (avoid duplicates)
        has_grade = any(g.get('courseName') == course_name for g in student_grades_data.get(student_id, []))
        has_attendance = any(a.get('courseName') == course_name for a in student_attendance_data.get(student_id, []))
        if has_grade or has_attendance:
             flash(f"Student {student_id} already appears to be associated with {course_name}.", "warning")
             return redirect(url_for('course_roster', course_name=course_name.replace(' ','+')))

        # Create a placeholder attendance record
        # Using a special status like "Enrolled" or just a default Present for simplicity?
        # Let's use Present for today's date for simplicity.
        from datetime import date
        today_date = date.today().strftime('%Y-%m-%d')

        new_record = {
            'studentId': student_id,
            'courseName': course_name,
            'date': today_date,
            'status': 'Present', # Or use 'Enrolled' if you prefer
            'instructor': faculty_name # Logged-in faculty adds them
        }

        # Append to CSV
        exists = os.path.isfile(ATTENDANCE_CSV); headers = ATTENDANCE_HEADERS
        write_h = not exists or os.path.getsize(ATTENDANCE_CSV) == 0
        with open(ATTENDANCE_CSV,'a',newline='',encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=headers, extrasaction='ignore');
            if write_h: w.writeheader();
            w.writerow(new_record)

        # Update memory
        if student_id not in student_attendance_data: student_attendance_data[student_id] = []
        student_attendance_data[student_id].append(new_record)

        flash(f"Student {student_id} added to {course_name} roster.", 'success')

    except Exception as e:
        flash(f"Error adding student to course: {e}", 'error')
        print(traceback.format_exc())
        # Redirect back to previous page if possible, otherwise course list
        return redirect(request.referrer or url_for('manage_courses'))

    # Redirect back to the specific course roster page
    return redirect(url_for('course_roster', course_name=course_name.replace(' ','+')))

# (Keep all other existing routes)
# ...

# --- Generic page renderer for static files (if any are left) ---
@app.route('/page/<page_name>')
@no_cache
def render_page(page_name):
    # Basic security: prevent access to sensitive files
    if '..' in page_name or page_name.startswith('/'):
        return "Invalid page name", 404
    try:
        return render_template(page_name)
    except:
         return "Page not found", 404


# =================================================================
# 8. Start the Server
# =================================================================
if __name__ == '__main__':
    # Try to load existing CSVs on startup
    # Load CSVs from /data directory (Render-friendly)
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    DATA_DIR = os.path.join(BASE_DIR, "data")

    # Load student profiles
    load_data_from_csv(os.path.join(DATA_DIR, "students.csv"), student_profile_data, 'studentId', is_list=False)

    # Populate login data
    student_login_data.clear()
    for student_id, profile in student_profile_data.items():
        if isinstance(profile, dict) and profile.get('password'):
            student_login_data[student_id] = {
                'password': profile['password'],
                'role': 'student'
            }

    # Load grades
    load_data_from_csv(os.path.join(DATA_DIR, "grades.csv"), student_grades_data, 'studentId', is_list=True)

    # Load attendance
    load_data_from_csv(os.path.join(DATA_DIR, "attendance.csv"), student_attendance_data, 'studentId', is_list=True)

    # Load courses
    try:
        load_data_from_csv(os.path.join(DATA_DIR, "courses.csv"), course_data, 'courseCode', is_list=False)
    except Exception as e:
        print(f"Warning: Could not load courses from courses.csv: {e}")


    print("\n--- Initial Data Loaded ---")
    print(f"Student Logins: {len(student_login_data)} loaded.")
    print(f"Student Profiles: {len(student_profile_data)} loaded.")
    print(f"Student Grades: {sum(len(v) for v in student_grades_data.values())} records loaded.")
    print(f"Student Attendance: {sum(len(v) for v in student_attendance_data.values())} records loaded.")
    print(f"Courses: {len(course_data)} loaded.")
    print("---------------------------\n")
    print(f"Student Logins: {len(student_login_data)} loaded.")
    print(f"Student Profiles: {len(student_profile_data)} loaded.")
    print(f"Student Grades: {sum(len(v) for v in student_grades_data.values())} records loaded.")
    print(f"Student Attendance: {sum(len(v) for v in student_attendance_data.values())} records loaded.")
    print("---------------------------\n")

    # Use host='0.0.0.0' to make accessible on local network if needed
    app.run(debug=True, port=5000)