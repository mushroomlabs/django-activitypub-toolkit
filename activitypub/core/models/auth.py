import uuid

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.db import models


def make_uid():
    return str(uuid.uuid4())


class UserManager(BaseUserManager):
    def create_user(self, *, password=None, **extra_fields):
        user = self.model(**extra_fields)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_superuser(self, *, password, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        return self.create_user(password=password, **extra_fields)


class ActorUser(AbstractBaseUser, PermissionsMixin):
    uid = models.CharField(max_length=30, default=make_uid, unique=True, editable=False)
    email = models.EmailField(null=True)

    banned = models.BooleanField(default=False)
    removed = models.BooleanField(default=False)

    objects = UserManager()

    USERNAME_FIELD = "uid"
    REQUIRED_FIELDS = []

    @property
    def is_staff(self):
        return False

    @property
    def is_superuser(self):
        return False

    def __str__(self):
        return self.uid
