#
# Copyright 2011 SuperKablamo, LLC
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
import utils

from settings import *
from django.utils import simplejson as json
from google.appengine.api import memcache
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

class Admin(MainHandler):
    def get(self, pswd=None):
        logging.info('################### Admin:: get() ####################')
        logging.info('################### pswd =' +pswd+ ' #################')        
        if pswd == "backyardchicken":
            categories = models.CategoryBean.all().fetch(100)
            template_values = {
                'categories': categories,
                'current_user': self.current_user,
                'facebook_app_id': FACEBOOK_APP_ID
            }  
            self.generate('base_admin.html', template_values)
        else: self.redirect(500)  

    def post(self, method=None):
        logging.info('################### Admin:: post() ###################')
        logging.info('################### method =' +method+' ##############')
        if method == "init-category-beans":
            initCategoryBeans()
        self.redirect('/admin/backyardchicken')  

class BaseHandler(MainHandler):
    """Returns content for the home page.
    """
    def get(self):
        # TODO: build lists of top users, categories and locations.
        logging.info("#############  BaseHandler:: get(self): ##############")
        logging.info("###### self.request.path= "+self.request.path+" ######")        
        category_leaders_cache = memcache.get(CAT_CACHE_ID) 
        location_leaders_cache = memcache.get(LOC_CACHE_ID)
        leaders_cache = memcache.get(LEAD_CACHE_ID)        
        if category_leaders_cache is None:
            category_leaders_cache = getCategoryLeaders()
            success = memcache.set(key=CAT_CACHE_ID, 
                                   value=category_leaders_cache, 
                                   time=300)

        if location_leaders_cache is None:   
            location_leaders_cache = getLocationLeaders()
            success = memcache.set(key=LOC_CACHE_ID, 
                                   value=location_leaders_cache, 
                                   time=300)
                                               
        if leaders_cache is None:                      
            leaders_cache = getLeaders() 
            success = memcache.set(key=LEAD_CACHE_ID, 
                                   value=leaders_cache, 
                                   time=300)   
                                            
        if isFacebook(self.request.path):
            count = 4
            template = "facebook/fb_base.html"            
        else:    
            count = 10
            template = "base.html"  
        deref_brags = getRecentBrags(count)
        self.generate(template, {
                      'host': self.request.host_url,        
                      'brags': deref_brags,
                      'leaders': leaders_cache,
                      'category_leaders': category_leaders_cache,
                      'location_leaders': location_leaders_cache,        
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
        category_leaders = getCategoryLeaders()
        location_leaders = getLocationLeaders()
        leaders = getLeaders()                
        if isFacebook(self.request.path):
            brags = brag_query.fetch(6)
            template = "facebook/fb_base_user_profile.html"            
        else:    
            brags = brag_query.fetch(10)
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
        category_beans = []
        for c in categories:
            key = db.Key.from_path('CategoryBean', utils.slugify(c))
            category_beans.append(key)
        share = self.request.get('facebook')        
        brag = models.Brag(user = user,
                           categories = categories,
                           category_beans = category_beans,
                           message = message,
                           origin = origin,
                           fb_location_id=user.fb_location_id,
                           fb_location_name=user.fb_location_name)
        brag.put()
        if share.upper() == 'TRUE': shareOnFacebook(self, user, brag)
        if isFacebook(self.request.path):
            self.redirect('/facebook/user/'+user_id)            
        else:    
            self.redirect('/user/'+user_id)  

class CategoryProfile(MainHandler):
    """Returns content for Category Profile pages.
    """    
    def get(self, category_slug=None):
        logging.info('################ CategoryProfile::get ################')
        user = self.current_user # this is the logged in User
        logging.info('######### category_slug = '+category_slug+' ##########')
        category_bean = models.CategoryBean.get_by_key_name(category_slug)
        logging.info('###### category_bean = '+str(category_bean)+' ########')
        category_leaders = getCategoryLeaders()
        location_leaders = getLocationLeaders()
        leaders = getLeaders()        
        if isFacebook(self.request.path):
            count = 4
            template = "facebook/fb_base_category_profile.html"            
        else:    
            count = 10
            template = "base_category_profile.html"
  
        deref_brags = getCategoryBrags(category_bean, count) 
        self.generate(template, {
                      'host': self.request.host_url, 
                      'category_bean': category_bean,    
                      'brags': deref_brags,
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

        location_bean = models.LocationBean.get_by_key_name(location_id)
        category_leaders = getCategoryLeaders()
        location_leaders = getLocationLeaders()
        leaders = getLeaders()        
        if isFacebook(self.request.path):
            count = 4
            template = "facebook/fb_base_location_profile.html"            
        else:    
            count = 10
            template = "base_location_profile.html"
            
        deref_brags = getLocationBrags(location_id, count)    
        self.generate(template, {
                      'host': self.request.host_url, 
                      'location_bean': location_bean,    
                      'brags': deref_brags,
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
        votee_fb_id = self.request.get('votee')
        voter = getFBUser(voter_fb_id)
        if voter.name is None: # Don't count any fake ids
            return
        votee = getFBUser(fb_id=votee_fb_id) # the profiled User   
        brag = models.Brag.get(brag_key)     
        awardBean(brag, voter, votee)    
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
    # Users need LocationBean records
    if user.fb_location_id is not None:
        location_beans = models.LocationBean.get_by_key_name(
                                                        user.fb_location_id)
        if location_beans is None:
            location_beans = models.LocationBean(
                                            key_name = user.fb_location_id,
                                            fb_id = user.fb_location_id,
                                            fb_name = user.fb_location_name,
                                            beans = 0)
            location_beans.put()           
    return user

def getCategoryBrags(category_bean, count):
    """Returns a list of *derefrenced* Brags for a specific Category ordered 
    by date desc.
    """
    brags_query = models.Brag.all().filter('categories =', category_bean.name)
    brags_query.order('-created')
    brags = brags_query.fetch(count)
    return utils.prefetch_refprops(brags, models.Brag.user)   
    
def getLocationBrags(location_id, count):
    """Returns a list of *derefrenced* Brags for a specific Category ordered 
    by date desc.
    """    
    brags_query = models.Brag.all().filter('fb_location_id =', location_id)
    brags_query.order('-created')
    brags = brags_query.fetch(count)
    return utils.prefetch_refprops(brags, models.Brag.user) 

def getRecentBrags(count):
    """Returns a list of *derefrenced* Brags ordered by date desc.
    """    
    brags_query = models.Brag.all().order('-created')
    brags = brags_query.fetch(count)
    if brags: return utils.prefetch_refprops(brags, models.Brag.user)
    else: return None

def getFBUser(fb_id=None):
    """Returns a User for the given fb_id.
    """
    logging.info("################ getFBUser("+fb_id+") ####################")
    user_query = models.User.all().filter('fb_id =', fb_id)
    user = user_query.get() # this is the profiled User
    return user

def getLeaders():
    memcache.delete(key=LEAD_CACHE_ID)    
    leaders_query = models.User.all().order('-beans')
    return leaders_query.fetch(10)    
        
def getCategoryLeaders():
    memcache.delete(key=CAT_CACHE_ID)
    category_leaders_query = models.CategoryBean.all().order('-beans')
    return category_leaders_query.fetch(10)
    
def getLocationLeaders():
    memcache.delete(key=LOC_CACHE_ID)
    location_leaders_query = models.LocationBean.all().order('-beans')
    return location_leaders_query.fetch(10)         

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
    attachment['link'] = FACEBOOK_URL+SITE+"/user/"+str(user.fb_id)
    attachment['description'] = "Earn points for going green.  See how you and your community measure up as stewards of the planet."
    attachment['picture'] = "http://willmerydith.storage.s3.amazonaws.com/avatars/facebook-wall-logo.png"
    vote_link = FACEBOOK_URL+SITE+"/user/"+str(user.fb_id)
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

def awardBean(brag, voter, votee):
    """Updates bean count for a Brag and associated Entities.
    """
    logging.info("###################### awardBean #########################")
    # Update Brag
    if brag is not None:
        if voter.fb_id not in brag.voter_keys:
            # This is a valid vote, so start updating Entities 
            # Update the Brag ...
            brag.voter_keys.append(voter.fb_id)
            brag.beans += 1
            brag.put()
            # Update the bean count for owner of the Brag getting a vote
            votee.beans += 1
            votee.put()    
            # Update the CategoryBeans  
            updated = []
            category_beans = models.CategoryBean.get(brag.category_beans)
            logging.info("## len(category_beans) = "+str(len(category_beans))+" #")
            for c in category_beans:
                logging.info("############ c.name = " +c.name+" ############")
                c.beans += 1
                updated.append(c)
            db.put(updated)    
            # Update the LocationBeans  
            loc_name = brag.fb_location_name
            loc_id = brag.fb_location_id
            loc_beans = models.LocationBean.get_by_key_name(loc_id)
            if loc_beans is not None:
                loc_beans.beans += 1
            else:
                loc_beans = models.LocationBean(key_name = loc_id,
                                                fb_id = loc_id,
                                                fb_name = loc_name,    
                                                beans = 1)
            loc_beans.put()    
    return     

def initCategoryBeans():
    """Seeds the datastore with CategoryBeans.
    """
    updated = []
    for c in CATS:
        key = db.Key.from_path('CategoryBean', c)
        cb = models.CategoryBean.get(key)
        if cb is None:
            cb = models.CategoryBean(key_name = CAT_SLUG[c],
                                     name = c,
                                     beans = 0,
                                     description=CAT_DESC[c],
                                     slug = CAT_SLUG[c])
            updated.append(cb)
    db.put(updated)                             
    return                             
        
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
                                              (r'/admin/(.*)', Admin),
                                              ('/', BaseHandler)],
                                              debug=DEBUG))
##############################################################################
############################################################################## 
if __name__ == "__main__":
    main()
