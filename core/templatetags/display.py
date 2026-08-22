from django import template

from core.services.naming import display_name

register = template.Library()


@register.filter(name="person")
def person(user):
    """模板里显示用户真实姓名：{{ item.owner|person }}。没填姓名时退回账号名。"""
    return display_name(user)
