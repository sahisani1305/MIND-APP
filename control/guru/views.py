from pymongo import MongoClient
from django.contrib.auth import authenticate, login as auth_login
from bson import ObjectId
from django.contrib.auth.models import User, Group
from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.utils import timezone


# MongoDB setup
client = MongoClient("mongodb://localhost:27017/")
db = client.mindmate_db

def index(request):
    return render(request, 'index.html')

def login_view(request):
    if request.method == 'POST':
        username = request.POST['username']
        password = request.POST['password']
        user = authenticate(request, username=username, password=password)
        
        if user is not None:
            auth_login(request, user)

            # Get the current date and time
            login_time = timezone.now().strftime('%Y-%m-%d %H:%M:%S')

            # Update the login times in the database
            db.logins.update_one(
                {'username': username},
                {'$push': {'login_times': login_time}},
                upsert=True
            )

            if user.is_superuser:
                return JsonResponse({'status': 'success', 'redirect': 'admin_page'})  # Redirect to admin page
            else:
                return JsonResponse({'status': 'success', 'redirect': 'user'})  # Redirect to user page
        else:
            return JsonResponse({'status': 'error', 'message': 'Invalid login credentials'}, status=400)
    else:
        return JsonResponse({'status': 'error', 'message': 'Method not allowed'}, status=405)

def signup_view(request):
    if request.method == 'POST':
        name = request.POST['name']
        email = request.POST['email']
        mobile = request.POST['mobile']
        age = request.POST['age']
        occupation = request.POST['occupation']
        username = request.POST['username']
        password = request.POST['password']
        
        # Check if username already exists
        if User.objects.filter(username=username).exists():
            return JsonResponse({'status': 'error', 'message': 'Username already exists'}, status=400)
        
        # Create user
        user = User.objects.create_user(username=username, email=email, password=password)
        user.first_name = name
        user.save()
        
        # Check if 'user' group exists, if not, create it
        group, created = Group.objects.get_or_create(name='user')
        
        # Add to 'user' group
        user.groups.add(group)
        
        # Save additional info to MongoDB
        user_data = {
            'name': name,
            'email': email,
            'mobile': mobile,
            'age': age,
            'occupation': occupation,
            'username': username
        }
        db.users.insert_one(user_data)
        
        # Return success response
        return JsonResponse({'status': 'success', 'message': 'Signup successful! Please login.'})
    else:
        return JsonResponse({'status': 'error', 'message': 'Method not allowed'}, status=405)
    
def admin_view(request):
    users = db.users.find()
    return render(request, 'admin.html', {'users': users})

def user_view(request):
    # Fetch the user's login times from the database
    user_logins = db.logins.find_one({'username': request.user.username})
    if user_logins:
        # Get only the unique dates
        login_times = list(set([login_time.split(' ')[0] for login_time in user_logins['login_times']]))
        login_times.sort()  # Sort the dates for better display
    else:
        login_times = []

    return render(request, 'users.html', {'login_times': login_times})

from django.shortcuts import render, redirect
from django.contrib.auth import logout

def logout_view(request):
    logout(request)
    return redirect('index')  # Redirect to the index page after logout
