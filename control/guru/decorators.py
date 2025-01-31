# decorators.py

from django.shortcuts import redirect
from django.http import HttpResponseForbidden

def admin_required(function):

    def wrap(request, *args, **kwargs):
        # Check if the user is authenticated and has an admin role
        if request.user.is_authenticated and request.user.is_superuser:
            return function(request, *args, **kwargs)
        # If not an admin, redirect to index page
        else:
            return redirect('index')  # Replace 'index' with the name of your index view
    
    return wrap
