import os
from pymongo import MongoClient
from bson import ObjectId
from django.contrib.auth import authenticate, login as auth_login, logout
from django.contrib.auth.models import User, Group
from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.utils import timezone
from django.contrib.auth.decorators import login_required
from django.conf import settings
from django.urls import reverse

# MongoDB setup
client = MongoClient("mongodb://localhost:27017/")
db = client.mindmate_db

def index(request):
    return render(request, 'index.html')

@login_required
def assessment(request):
    today = timezone.now().strftime('%Y-%m-%d')
    existing_assessment = db.assessments.find_one({
        'username': request.user.username,
        'timestamp': {'$gte': timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)}
    })

    if existing_assessment:
        return render(request, 'assessment.html', {'message': 'You have already taken the assessment today. Please come back tomorrow for a retest.'})

    if request.method == 'POST':
        scores = {'depression': 0, 'anxiety': 0, 'stress': 0}
        question_categories = {
            'depression': [3, 5, 10, 13, 16, 17, 21],
            'anxiety': [2, 4, 7, 9, 15, 19, 20],
            'stress': [1, 6, 8, 11, 12, 14, 18]
        }

        for category, questions in question_categories.items():
            for q_num in questions:
                question_key = f'q{q_num}'
                scores[category] += int(request.POST.get(question_key, 0))

        scores = {k: v * 2 for k, v in scores.items()}

        def get_severity(score, category):
            if category == 'depression':
                if score <= 9:
                    return 'Normal'
                elif score <= 13:
                    return 'Mild'
                elif score <= 20:
                    return 'Moderate'
                elif score <= 27:
                    return 'Severe'
                else:
                    return 'Extremely Severe'
            elif category == 'anxiety':
                if score <= 7:
                    return 'Normal'
                elif score <= 9:
                    return 'Mild'
                elif score <= 14:
                    return 'Moderate'
                elif score <= 19:
                    return 'Severe'
                else:
                    return 'Extremely Severe'
            elif category == 'stress':
                if score <= 14:
                    return 'Normal'
                elif score <= 18:
                    return 'Mild'
                elif score <= 25:
                    return 'Moderate'
                elif score <= 33:
                    return 'Severe'
                else:
                    return 'Extremely Severe'

        severity = {
            'depression': get_severity(scores['depression'], 'depression'),
            'anxiety': get_severity(scores['anxiety'], 'anxiety'),
            'stress': get_severity(scores['stress'], 'stress'),
        }

        db.assessments.insert_one({
            'username': request.user.username,
            'depression': scores['depression'],
            'anxiety': scores['anxiety'],
            'stress': scores['stress'],
            'severity': severity,
            'timestamp': timezone.now()
        })

        return redirect('user_view')

    return render(request, 'assessment.html')

def login_view(request):
    if request.method == 'POST':
        username = request.POST['username']
        password = request.POST['password']
        user = authenticate(request, username=username, password=password)
        
        if user is not None:
            auth_login(request, user)
            login_time = timezone.now().strftime('%Y-%m-%d %H:%M:%S')
            db.logins.update_one(
                {'username': username},
                {'$push': {'login_times': login_time}},
                upsert=True
            )

            if user.is_superuser:
                return JsonResponse({'status': 'success', 'redirect': 'admin_page'})
            else:
                return JsonResponse({'status': 'success', 'redirect': 'user'})
        else:
            return JsonResponse({'status': 'error', 'message': 'Invalid login credentials'}, status=400)
    else:
        return JsonResponse({'status': 'error', 'message': 'Method not allowed'}, status=405)
from django.shortcuts import render
from django.http import JsonResponse
from django.contrib.auth.models import User, Group
def signup_view(request):
    if request.method == 'POST':
        name = request.POST.get('name', None)
        email = request.POST.get('email', None)
        mobile = request.POST.get('mobile', None)
        age = request.POST.get('age', None)
        occupation = request.POST.get('occupation', None)
        username = request.POST.get('username', None)
        password = request.POST.get('password', None)
        gender = request.POST.get('gender', None)

        if not all([name, email, mobile, age, occupation, username, password, gender]):
            return JsonResponse({'status': 'error', 'message': 'All fields are required.'}, status=400)

        if User.objects.filter(username=username).exists():
            return JsonResponse({'status': 'error', 'message': 'Username already exists'}, status=400)

        if db.users.find_one({'email': email}):
            return JsonResponse({'status': 'error', 'message': 'Email already exists'}, status=400)

        if db.users.find_one({'mobile': mobile}):
            return JsonResponse({'status': 'error', 'message': 'Mobile number already exists'}, status=400)

        user = User.objects.create_user(username=username, email=email, password=password)
        user.first_name = name
        user.save()

        group, created = Group.objects.get_or_create(name='user')
        user.groups.add(group)

        user_data = {
            'name': name,
            'email': email,
            'mobile': mobile,
            'age': age,
            'occupation': occupation,
            'username': username,
            'gender': gender
        }
        db.users.insert_one(user_data)

        return JsonResponse({'status': 'success', 'message': 'Signup successful! Please login.'})
    else:
        return JsonResponse({'status': 'error', 'message': 'Method not allowed'}, status=405)
    
from django.shortcuts import render, redirect

def admin_view(request):
    users = list(db.users.find())
    for user in users:
        user['id_str'] = str(user['_id'])  # Create a new field 'id_str' that holds the string version of '_id'

    if request.method == 'POST':
        user_id = request.POST.get('user_id')
        if user_id:
            try:
                # Delete user from MongoDB
                db.users.delete_one({'_id': ObjectId(user_id)})
                
                # Also delete user from Django admin
                # Assuming you have a matching user in Django with the same email or username
                django_user = User.objects.filter(email=user.email).first()
                if django_user:
                    django_user.delete()
            except Exception as e:
                print(e)
        return redirect('admin_page')  # Replace 'admin_view' with your actual URL name

    return render(request, 'admin.html', {'users': users})

from datetime import datetime

@login_required
def user_view(request):
    user_data = db.users.find_one({'username': request.user.username})
    profile_image_url = user_data.get('profile_image_url', None) if user_data else None

    user_logins = db.logins.find_one({'username': request.user.username})
    if user_logins:
        unique_dates = set()
        login_times = []
        for login_time in user_logins['login_times']:
            date, time = login_time.split(' ')
            if date not in unique_dates:
                unique_dates.add(date)
                login_times.append({'date': date, 'time': time})
        login_times.sort(key=lambda x: x['date'])
    else:
        login_times = []

    assessments = db.assessments.find({'username': request.user.username}).sort('timestamp', 1)
    scores_by_date = {}
    for assessment in assessments:
        date = assessment['timestamp'].strftime('%Y-%m-%d')
        if date not in scores_by_date:
            scores_by_date[date] = {
                'depression': 0,
                'anxiety': 0,
                'stress': 0,
            }
        scores_by_date[date]['depression'] = assessment['depression']
        scores_by_date[date]['anxiety'] = assessment['anxiety']
        scores_by_date[date]['stress'] = assessment['stress']

    daily_scores = []
    for date, scores in sorted(scores_by_date.items()):
        daily_scores.append({
            'date': date,
            'depression': scores['depression'],
            'anxiety': scores['anxiety'],
            'stress': scores['stress'],
        })

    latest_assessment = db.assessments.find_one({'username': request.user.username}, sort=[('timestamp', -1)])
    scores = latest_assessment if latest_assessment else None
    severity = latest_assessment['severity'] if latest_assessment else None
    latest_assessment_date = latest_assessment['timestamp'].strftime('%Y-%m-%d') if latest_assessment else None

    # Check if the latest assessment date is today
    today_date = datetime.now().strftime('%Y-%m-%d')
    has_taken_assessment_today = (latest_assessment_date == today_date)

    return render(request, 'users.html', {
        'profile_image_url': profile_image_url,
        'login_times': login_times,
        'scores': scores,
        'severity': severity,
        'daily_scores': daily_scores,
        'latest_assessment_date': latest_assessment_date,
        'has_taken_assessment_today': has_taken_assessment_today,
        'user_data': user_data  # Add the user data to the context
    })

def logout_view(request):
    @login_required
    def get_user_info(request):
        user_data = db.users.find_one({'username': request.user.username}, {'_id': 0, 'name': 1, 'username': 1, 'email': 1, 'mobile': 1, 'age': 1, 'occupation': 1, 'gender': 1})
        if user_data:
            return JsonResponse({'status': 'success', 'data': user_data})
        else:
            return JsonResponse({'status': 'error', 'message': 'User not found'}, status=404)
    logout(request)
    return redirect('index')

@login_required
def upload_profile_image(request):
    if request.method == 'POST':
        profile_image = request.FILES.get('profile_image')
        if profile_image:
            profile_images_dir = os.path.join(settings.MEDIA_ROOT, 'profile_images')
            os.makedirs(profile_images_dir, exist_ok=True)

            path = os.path.join(profile_images_dir, profile_image.name)
            with open(path, 'wb+') as destination:
                for chunk in profile_image.chunks():
                    destination.write(chunk)

            profile_image_url = f'/media/profile_images/{profile_image.name}'
            db.users.update_one(
                {'username': request.user.username},
                {'$set': {'profile_image_url': profile_image_url}}
            )
            
            print(f"Profile image saved to: {path}")
            print(f"Profile image URL: {profile_image_url}")
            
            return JsonResponse({'success': True})
    return JsonResponse({'success': False})
