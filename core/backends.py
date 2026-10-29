from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend


class EmailOrUsernameBackend(ModelBackend):
    """Sign in with either the username (login) or the email address."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None or password is None:
            return None
        User = get_user_model()
        user = (
            User.objects.filter(username__iexact=username).first()
            or User.objects.filter(email__iexact=username).first()
        )
        if user is None:
            User().set_password(password)  # same timing as a real check
            return None
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
