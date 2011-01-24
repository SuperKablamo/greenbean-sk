from google.appengine.ext.webapp import template
from django import template as django_template

def in_list(value, arg):
  """
  Given an item and a list, check if the item is in the list.
  Usage:
  {% if item|in_list:list %} 
      in list 
  {% else %} 
      not in list
  {% endif %}
  """
  return value in arg
  
register = template.create_template_register()  
ifinlist = register.filter(in_list)

