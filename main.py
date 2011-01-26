#
# Copyright 2010 SuperKablamo, LLC
# info@superkablamo.com
#
############################# IMPORTS ########################################
############################################################################## 
import base64
import cgi
import Cookie
import email.utils
import hashlib
import hmac
import logging
import os.path
import time
import urllib
import wsgiref.handlers
import models
import facebook
import re

from settings import *
from django.utils import simplejson as json
from google.appengine.ext import db
from google.appengine.ext import webapp
from google.appengine.ext.webapp import util
from google.appengine.ext.webapp import template

############################# REQUEST HANDLERS ###############################    
############################################################################## 
class MainHandler(webapp.RequestHandler):
    """Provides access to the active Facebook user in self.current_user

    The property is lazy-loaded on first access, using the cookie saved
    by the Facebook JavaScript SDK to determine the user ID of the active
    user. See http://developers.facebook.com/docs/authentication/ for
    more information.
    """
    @property
    def current_user(self):
        logging.info('########### BaseHandler:: current_user ###########')

        cookie = facebook.get_user_from_cookie(
            self.request.cookies, FACEBOOK_APP_ID, FACEBOOK_APP_SECRET
        )
        #Sam - checking to see if we have a FB cookie
        # If the user is logged out of FB - set the _current_user to None
        if not cookie:
            self._current_user = None
            
        if not hasattr(self, "_current_user"):
            self._current_user = None
            cookie = facebook.get_user_from_cookie(
                self.request.cookies, FACEBOOK_APP_ID, FACEBOOK_APP_SECRET)
            if cookie:
                # Store a local instance of the user data so we don't need
                # a round-trip to Facebook on every request
                user = models.User.get_by_key_name(cookie["uid"])
                if not user: # Build a User
                    logging.info("Building a user")
                    user = getUser(
                            facebook.GraphAPI(cookie["access_token"]),
                            cookie)
                    logging.info("User built: " + user.name)
                elif user.access_token != cookie["access_token"]:
                    user.access_token = cookie["access_token"]
                    user.put()
                self._current_user = user
        return self._current_user
    
    def generate(self, template_name, template_values):
        template.register_template_library('templatefilters')
        directory = os.path.dirname(__file__)
        path = os.path.join(directory, 
                            os.path.join('templates', template_name))

        #Sam - setting the headers for IE IFrame bug
        self.response.headers["P3P"] = 'CP="IDC CURa ADMa OUR IND PHY ONL COM STA"'                            
        self.response.out.write(template.render(path, 
                                                template_values, 
                                                debug=DEBUG))

class BaseHandler(MainHandler):
    """Returns content for the home page.
    """
    def get(self):
        # TODO: build lists of top users, categories and locations.
        logging.info("#############  BaseHandler:: get(self): ##############")
        logging.info("############# self.request.path="+self.request.path+" ##############")        
        category_leaders = getCategoryLeaders()
        location_leaders = getLocationLeaders()
        leaders = getLeaders() 
        if isFacebook(self.request.path):
            brags = getRecentBrags(4)
            template = "facebook/fb_base.html"            
        else:    
            brags = getRecentBrags(10)
            template = "base.html"  
        self.generate(template, {
                      'host': self.request.host_url,        
                      'brags': brags,
                      'leaders': leaders,
                      'category_leaders': category_leaders,
                      'location_leaders': location_leaders,        
                      'current_user':self.current_user,
                      'facebook_app_id':FACEBOOK_APP_ID})
                   
class UserProfile(MainHandler):
    """Returns content for User Profile pages.
    """
    def get(self, user_id=None):
        logging.info('################# UserProfile::get ###################')
        user = self.current_user # this is the logged in User
        profile_user = getFBUser(fb_id=user_id) # this is the profiled User
        brag_query = models.Brag.all().order('-created')
        brag_query = brag_query.filter('user', profile_user)
        brags = brag_query.fetch(10)
        category_leaders = getCategoryLeaders()
        location_leaders = getLocationLeaders()
        leaders = getLeaders()                
        if isFacebook(self.request.path):
            template = "facebook/fb_base_user_profile.html"            
        else:    
            template = "base_user_profile.html"
        
        self.generate(template, {
                      'host': self.request.host_url, 
                      'brags': brags,
                      'profile_user': profile_user,
                      'categories': CATS,
                      'leaders': leaders,
                      'category_leaders': category_leaders,
                      'location_leaders': location_leaders,
                      'current_user': self.current_user,
                      'facebook_app_id':FACEBOOK_APP_ID}) 
                      
    def post(self, user_id=None):
        """POSTs a new Brag.
        """
        logging.info('################## UserProfile::post #################')
        user = getFBUser(user_id) # this is the profiled User
        message = self.request.get('message')
        origin = self.request.get('origin')
        categories = self.request.get_all('category')
        share = self.request.get('facebook')        
        brag = models.Brag(user = user,
                           categories = categories,
                           message = message,
                           origin = origin,
                           fb_location_id=user.fb_location_id,
                           fb_location_name=user.fb_location_name)
        brag.put()
        if share.upper() == 'TRUE': shareOnFacebook(self, user, brag)
        self.redirect('/user/'+user_id)  
        return          

class CategoryProfile(MainHandler):
    """Returns content for Category Profile pages.
    """    
    def get(self, category=None):
        logging.info('################ CategoryProfile::get ################')
        user = self.current_user # this is the logged in User
        brags = getCategoryBrags(category)
        category_beans = models.CategoryBeans.get_by_key_name(category)
        category_leaders = getCategoryLeaders()
        location_leaders = getLocationLeaders()
        leaders = getLeaders()        
        if isFacebook(self.request.path):
            template = "facebook/fb_base_category_profile.html"            
        else:    
            template = "base_category_profile.html"
            
        self.generate(template, {
                      'host': self.request.host_url, 
                      'category': category,    
                      'category_beans': category_beans,    
                      'brags': brags,
                      'leaders': leaders,
                      'category_leaders': category_leaders,
                      'location_leaders': location_leaders,
                      'current_user':self.current_user,
                      'facebook_app_id':FACEBOOK_APP_ID})  
    
class LocationProfile(MainHandler):
    """Returns content for Location Profile pages.
    """    
    def get(self, location_id=None):
        logging.info('################ LocationProfile::get ################')
        user = self.current_user # this is the logged in User
        brags = getLocationBrags(location_id)
        location_beans = models.LocationBeans.get_by_key_name(location_id)
        category_leaders = getCategoryLeaders()
        location_leaders = getLocationLeaders()
        leaders = getLeaders()        
        if isFacebook(self.request.path):
            template = "facebook/fb_base_location_profile.html"            
        else:    
            template = "base_location_profile.html"
            
        self.generate(template, {
                      'host': self.request.host_url, 
                      'location_beans': location_beans,    
                      'brags': brags,
                      'leaders': leaders,
                      'category_leaders': category_leaders,
                      'location_leaders': location_leaders,
                      'current_user':self.current_user,
                      'facebook_app_id':FACEBOOK_APP_ID})  

class Bean(MainHandler):
    """Updates bean count for a Brag and associated Categories, Users and
    Locations.
    """
    def post(self):    
        logging.info('################ Bean::post ##########################') 
        brag_key = self.request.get('brag') 
        voter_fb_id = self.request.get('voter')
        if isSpam(voter_fb_id): # Don't count any fake ids
            return
        votee_fb_id = self.request.get('votee')
        votee_user = getFBUser(fb_id=votee_fb_id) # the profiled User
        # Update Brag
        brag = models.Brag.get(brag_key)
        if brag is not None:
            if voter_fb_id not in brag.voter_keys:
                # This is a valid vote, so start updating Entities 
                # Update the Brag ...
                brag.voter_keys.append(voter_fb_id)
                brag.beans += 1
                brag.put()
                # Update the bean count for owner of the Brag getting a vote
                votee_user.beans += 1
                votee_user.put()    
                # Update the CategoryBeans  
                for c in brag.categories:
                    cat_beans = models.CategoryBeans.get_by_key_name(c)
                    if cat_beans is not None:
                        cat_beans.beans += 1
                    else:
                        cat_beans = models.CategoryBeans(key_name = c,
                                                         name = c,    
                                                         beans = 1)
                    cat_beans.put()
                # Update the LocationBeans  
                loc_name = brag.fb_location_name
                loc_id = brag.fb_location_id
                loc_beans = models.LocationBeans.get_by_key_name(loc_id)
                if loc_beans is not None:
                    loc_beans.beans += 1
                else:
                    loc_beans = models.LocationBeans(key_name = loc_id,
                                                     fb_id = loc_id,
                                                     fb_name = loc_name,    
                                                     beans = 1)
                loc_beans.put()    
        return

class Page(MainHandler):
    """Returns content for a User Sign Up page.
    """   
    def get(self, page=None):
        path = ""
        if isFacebook(self.request.path):
            path = "facebook/fb_"            
        if page == "signup":
            template = path+"base_signup.html"
        elif page == "about":
            template = path+"base_about.html"    
        elif page == "contact":
            template = path+"base_contact.html"
        elif page == "rewards":
            template = path+"base_rewards.html"                           
        elif page == "terms":
            template = path+"base_terms.html"        
        else:
            template = path+"base_404.html"   
        logging.info("############### template ="+template+" ###############")    
        self.generate(template, {
                      'host': self.request.host_url, 
                      'current_user':self.current_user,
                      'facebook_app_id':FACEBOOK_APP_ID})        

############################### METHODS ######################################
############################################################################## 
def getUser(graph, cookie):
    """Returns a User model, built from the Facebook Graph API data.  Also, 
    a UserBean and LocationBean entity is created or updated to ensure 
    referenced "de-normalized" data is in sync.
    """
    # Build User from Facebook Graph API ...
    profile = graph.get_object("me")
    try: # If the user has no location set, make the default "Earth"
        loc_id = fb_location_id=profile["location"]["id"]
        loc_name = fb_location_name=profile["location"]["name"]
    except KeyError:
        loc_id = "000000000000001"
        loc_name = "Earth"    
    user = models.User(key_name=str(profile["id"]),
                       fb_id=str(profile["id"]),
                       name=profile["name"],
                       fb_profile_url=profile["link"],
                       fb_location_id=loc_id, #profile["location"]["id"],
                       fb_location_name=loc_name, #profile["location"]["name"],
                       access_token=cookie["access_token"])
                       
    user.put() 
    # Users need UserBean records ...
    user_beans = models.UserBeans.get_by_key_name(user.fb_id)
    if user_beans is None:
        user_beans = models.UserBeans(user = user,
                                      key_name = user.fb_id,
                                      beans = 0)
        user_beans.put()  
    # Users need LocationBean records
    if user.fb_location_id is not None:
        location_beans = models.LocationBeans.get_by_key_name(
                                                        user.fb_location_id)
        if location_beans is None:
            location_beans = models.LocationBeans(
                                            key_name = user.fb_location_id,
                                            fb_id = user.fb_location_id,
                                            fb_name = user.fb_location_name,
                                            beans = 0)
            location_beans.put()           
    return user

def getCategoryBrags(category):
    """Returns a list of Brags for a specific Category ordered by date desc.
    """
    brags_query = models.Brag.all().filter('categories =', category)
    brags_query.order('-created')
    return brags_query.fetch(10)
    
def getLocationBrags(location_id):
    """Returns a list of Brags for a specific Category ordered by date desc.
    """    
    brags_query = models.Brag.all().filter('fb_location_id =', location_id)
    brags_query.order('-created')
    return brags_query.fetch(10)    

def getFBUser(fb_id=None):
    """Returns a User for the given fb_id.
    """
    logging.info("################ getFBUser("+fb_id+") ####################")
    user_query = models.User.all().filter('fb_id =', fb_id)
    user = user_query.get() # this is the profiled User
    return user

def getLeaders():
    leaders_query = models.User.all().order('-beans')
    return leaders_query.fetch(10)    
        
def getCategoryLeaders():
    category_leaders_query = models.CategoryBeans.all().order('-beans')
    return category_leaders_query.fetch(10)
    
def getLocationLeaders():
    location_leaders_query = models.LocationBeans.all().order('-beans')
    return location_leaders_query.fetch(10)         

def getRecentBrags(count):
    brags_query = models.Brag.all().order('-created')
    return brags_query.fetch(count)    

def shareOnFacebook(self, user, brag):
    categories = []
    categories.append("  Categories: ")
    for c in brag.categories:
        categories.append("#"+c+"  ")
    message = brag.message + ''.join(categories) 
    #message = brag.message
    attachment = {}
    attachment['caption'] = "How are you helping the planet?"
    attachment['name'] = "Go Green!"
    attachment['link'] = FACEBOOK_URL+SITE
    attachment['description'] = "Earn points for going green.  See how you and your community measure up as stewards of the planet."
    attachment['picture'] = "http://willmerydith.storage.s3.amazonaws.com/avatars/facebook-wall-logo.png"
    vote_link = FACEBOOK_URL+SITE
    actions = {"name": "Vote for this.", "link": vote_link}
    attachment['actions'] = actions
    results = facebook.GraphAPI(
        user.access_token).put_wall_post(message, attachment)
    return str(results['id'])
    
def isFacebook(path):
    """Returns True if request is from a Facebook iFrame, otherwise False.
    """
    if re.search(r".facebook\.*", path): # match a Facebook apps uri
        logging.info("############### facebook detected! ###############")
        return True
    else:
        logging.info("############### facebook NOT detected! ###########")        
        return False      

def isSpam(user_fb_id):
    user = models.User.get_by_key_name(user_fb_id)
    if user.name is not None: # User's w/out name have bypassed Facebook login
        return False
    else:
        return True
        
##############################################################################
############################################################################## 
def main():
    util.run_wsgi_app(webapp.WSGIApplication([(r'/page/(.*)', Page),
                                              (r'/user/(.*)', UserProfile),
                                              (r'/category/(.*)', CategoryProfile),  
                                              (r'/location/(.*)', LocationProfile),
                                              (r'/facebook/page/(.*)', Page),
                                              (r'/facebook/user/(.*)', UserProfile),
                                              (r'/facebook/category/(.*)', CategoryProfile),  
                                              (r'/facebook/location/(.*)', LocationProfile), 
                                              ('/bean', Bean),
                                              ('/facebook/', BaseHandler),
                                              ('/', BaseHandler)],
                                              debug=DEBUG))
##############################################################################
############################################################################## 
if __name__ == "__main__":
    main()
