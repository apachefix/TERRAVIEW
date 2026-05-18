from apps.home.models import *

def get_users_active(request):
    users = User.objects.filter(is_active=True).exclude(id = request.user.id).order_by('username')
    return {"users_active": users}