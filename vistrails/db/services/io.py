############################################################################
##
## Copyright (C) 2006-2010 University of Utah. All rights reserved.
##
## This file is part of VisTrails.
##
## This file may be used under the terms of the GNU General Public
## License version 2.0 as published by the Free Software Foundation
## and appearing in the file LICENSE.GPL included in the packaging of
## this file.  Please review the following to ensure GNU General Public
## Licensing requirements will be met:
## http://www.opensource.org/licenses/gpl-license.php
##
## If you are unsure which license is appropriate for your use (for
## instance, you are interested in developing a commercial derivative
## of VisTrails), please contact us at vistrails@sci.utah.edu.
##
## This file is provided AS IS with NO WARRANTY OF ANY KIND, INCLUDING THE
## WARRANTY OF DESIGN, MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE.
##
############################################################################

from datetime import datetime
from core import debug
from core.bundles import py_import
from core.system import get_elementtree_library, temporary_directory,\
     execute_cmdline, systemType
import core.requirements
ElementTree = get_elementtree_library()

import sys
import os
import os.path
import shutil
import tempfile
import copy

from db import VistrailsDBException
from db.domain import DBVistrail, DBWorkflow, DBLog, DBAbstraction, DBGroup, \
    DBRegistry, DBWorkflowExec, DBOpmGraph
import db.services.abstraction
import db.services.log
import db.services.opm
import db.services.registry
import db.services.workflow
import db.services.vistrail
from db.versions import getVersionDAO, currentVersion, getVersionSchemaDir, \
    translate_object, translate_vistrail, translate_workflow, translate_log, \
    translate_registry

_db_lib = None
def get_db_lib():
    global _db_lib
    if _db_lib is None:
        # FIXME use core.bundles.py_import here
        import MySQLdb
        # import sqlite3
        _db_lib = MySQLdb
    return _db_lib
def set_db_lib(lib):
    global _db_lib
    _db_lib = lib

# load MySQLdb early if it exists, o/w don't error out
try:
    get_db_lib()
except ImportError:
    pass

class SaveBundle(object):
    """Transient bundle of objects to be saved or loaded.
       The bundle type MUST be specified in the constructor; it should be
       the the vtType of the primary object in the bundle. This parameter
       identifies which object is the primary object when mutiple objects
       are stored in the bundle.

       Args is the (unordered) list of objects to be included in the bundle
       (vistrail, workflow, log, registry, opm_graph).  Any args without a
       'vtType' attribute are explicitly ignored (including any args=None).

       As kwargs, you can specify 'abstractions=[]' or 'thumbnails=[]',
       both of which should be a list of filenames as strings.  You can also
       specify the other bundle objects as kwargs, but abstractions and
       thumbnails cannot be args, since they are both lists, and there is no
       vtType to differentiate between them.

       As a final option, you can directly set the objects in the bundle,
       self.vistrail = vistrail_object, self.thumbnails = thumbs_list, etc.,
       before passing the SaveBundle to a locator.  Both abstractions and
       thumbnails are intialized for convenience so that you can directly
       append to them when using this step-by-step bundle creation method.

    """

    def __init__(self, bundle_type, *args, **kwargs):
        self.bundle_type = bundle_type
        self.vistrail = None
        self.workflow = None
        self.log = None
        self.registry = None
        self.opm_graph = None
        self.abstractions = []
        self.thumbnails = []
        # Make all args into attrs using vtType as attr name
        # This requires that attr names in this class match the vtTypes
        # i.e. if arg's vtType is 'vistrail', self.vistrail = arg, etc...
        for arg in args:
            if hasattr(arg, 'vtType'):
                setattr(self, arg.vtType, arg)
        # Make all keyword args directly into attrs
        for (k,v) in kwargs.iteritems():
            setattr(self, k, v)

    def get_db_objs(self):
        """Gets a list containing only the DB* objects in the bundle"""
        return [obj for obj in self.__dict__.itervalues() if obj is not None and type(obj) not in [type([]), type('')]]

    def get_primary_obj(self):
        """get_primary_obj() -> DB*
           Gets the bundle's primary DB* object based on the bundle type.
        """
        return getattr(self, self.bundle_type)

    def __copy__(self):
        return SaveBundle.do_copy(self)
    
    def do_copy(self):
        cp = SaveBundle(self.bundle_type)
        cp.vistrail = copy.copy(self.vistrail)
        cp.workflow = copy.copy(self.workflow)
        cp.log = copy.copy(self.log)
        cp.registry = copy.copy(self.registry)
        cp.opm_graph = copy.copy(self.opm_graph)
        for a in self.abstractions:
            cp.abstractions.append(a)
        
        for t in self.thumbnails:
            cp.thumbnails.append(t)
        
        return cp

def format_prepared_statement(statement):
    """format_prepared_statement(statement: str) -> str
    Formats a prepared statement for compatibility with the currently
    loaded database library's paramstyle.

    Currently only supports 'qmark' and 'format' paramstyles.
    May be expanded later to allow for more compatibility options
    on input and output.  See PEP 249 for more info.

    """
    style = get_db_lib().paramstyle
    if style == 'format':
        return statement.replace("?", "%s")
    elif style == 'qmark':
        return statement.replace("%s", "?")
    return statement

def open_db_connection(config):

    if config is None:
        msg = "You need to provide valid config dictionary"
        raise VistrailsDBException(msg)
    try:
        # FIXME allow config to be kwargs and args?
        db_connection = get_db_lib().connect(**config)
        #db_connection = get_db_lib().connect(config)
        return db_connection
    except get_db_lib().Error, e:
        # should have a DB exception type
        msg = "cannot open connection (%d: %s)" % (e.args[0], e.args[1])
        raise VistrailsDBException(msg)

def close_db_connection(db_connection):
    if db_connection is not None:
        db_connection.close()

def test_db_connection(config):
    """testDBConnection(config: dict) -> None
    Tests a connection raising an exception in case of error.
    
    """
    try:
        db_connection = get_db_lib().connect(**config)
        close_db_connection(db_connection)
    except get_db_lib().Error, e:
        msg = "connection test failed (%d: %s)" % (e.args[0], e.args[1])
        raise VistrailsDBException(msg)

def ping_db_connection(db_connection):
    """ping_db_connection(db_connection) -> boolean 
    It will ping the database to check if the connection is alive.
    It returns True if it is, False otherwise. 
    This can be used for preventing the "MySQL Server has gone away" error. 
    """
    try:
        db_connection.ping()
    except get_db_lib().OperationalError, e:
        return False
    return True
    
def translate_to_tbl_name(obj_type):
    map = {DBVistrail.vtType: 'vistrail',
           DBWorkflow.vtType: 'workflow',
           DBLog.vtType: 'log_tbl',
           DBRegistry.vtType: 'registry',
           DBAbstraction.vtType: 'abstraction',
           }
    return map[obj_type]

def date_to_str(date):
    return date.strftime('%Y-%m-%d %H:%M:%S')

def get_db_object_list(config, obj_type):
    
    result = []    
    db = open_db_connection(config)

    #FIXME Create a DBGetVistrailListSQLDAOBase for this
    # and maybe there's another way to build this query
    command = """SELECT o.id, o.name, o.last_modified
    FROM %s o
    ORDER BY o.name
    """
#     command = """SELECT o.id, v.name, a.date, a.user
#     FROM %s o, action a,
#     (SELECT a.entity_id, MAX(a.date) as recent, a.user
#     FROM action a
#     GROUP BY entity_id) latest
#     WHERE o.id = latest.entity_id 
#     AND a.entity_id = o.id
#     AND a.date = latest.recent 
#     """ % obj_type

    try:
        c = db.cursor()
        c.execute(command % translate_to_tbl_name(obj_type))
        rows = c.fetchall()
        result = rows
        c.close()
        close_db_connection(db)
        
    except get_db_lib().Error, e:
        msg = "Couldn't get list of vistrails objects from db (%d : %s)" % \
            (e.args[0], e.args[1])
        raise VistrailsDBException(msg)
    return result

def get_db_object_modification_time(db_connection, obj_id, obj_type):
    command = """
    SELECT o.last_modified
    FROM %s o
    WHERE o.id = %s
    """

    try:
        db_connection.begin()
        c = db_connection.cursor()
        c.execute(command % (translate_to_tbl_name(obj_type), obj_id))
        db_connection.commit()
        time = c.fetchall()[0][0]
        c.close()
    except get_db_lib().Error, e:
        msg = "Couldn't get object modification time from db (%d : %s)" % \
            (e.args[0], e.args[1])
        raise VistrailsDBException(msg)
    return time

def get_db_object_version(db_connection, obj_id, obj_type):
    command = """
    SELECT o.version
    FROM %s o
    WHERE o.id = %s
    """

    try:
        c = db_connection.cursor()
        #print command % (translate_to_tbl_name(obj_type), obj_id)
        c.execute(command % (translate_to_tbl_name(obj_type), obj_id))
        version = c.fetchall()[0][0]
        c.close()
    except get_db_lib().Error, e:
        msg = "Couldn't get object version from db (%d : %s)" % \
            (e.args[0], e.args[1])
        raise VistrailsDBException(msg)
    return version

def get_db_version(db_connection):
    command = """
    SELECT `version`
    FROM `vistrails_version`
    """

    try:
        c = db_connection.cursor()
        c.execute(command)
        version = c.fetchall()[0][0]
        c.close()
    except get_db_lib().Error, e:
        # just return None if we hit an error
        return None
    return version

def get_db_id_from_name(db_connection, obj_type, name):
    command = """
    SELECT o.id 
    FROM %s o
    WHERE o.name = '%s'
    """

    try:
        c = db_connection.cursor()
        c.execute(command % (translate_to_tbl_name(obj_type), name))
        rows = c.fetchall()
        if len(rows) != 1:
            if len(rows) == 0:
                c.close()
                msg = "Cannot find object of type '%s' named '%s'" % \
                    (obj_type, name)
                raise VistrailsDBException(msg)
            elif len(rows) > 1:
                c.close()
                msg = "Found more than one object of type '%s' named '%s'" % \
                    (obj_type, name)
                raise VistrailsDBException(msg)
        else:
            c.close()
            return int(rows[0][0])
    except get_db_lib().Error, e:
        c.close()
        msg = "Connection error when trying to get db id from name"
        raise VisrailsDBException(msg)

def get_matching_abstraction_id(db_connection, abstraction):
    last_action_id = -1
    last_action = None
    for action in abstraction.db_actions:
        if action.db_id > last_action_id:
            last_action_id = action.db_id
            last_action = action

    command = """
    SELECT g.id 
    FROM abstraction g, action a
    WHERE g.name = '%s'
    AND a.entity_type = 'abstraction'
    AND a.entity_id = g.id
    AND a.user = '%s'
    AND a.date = '%s'
    AND a.id = %s
    """
    
    id = None
    try:
        c = db_connection.cursor()
        c.execute(command % (abstraction.db_name,
                             last_action.db_user,
                             date_to_str(last_action.db_date),
                             last_action.db_id))
        result = c.fetchall()
        c.close()
        if len(result) > 0:
            print 'got result:', result
            id = result[0][0]
    except get_db_lib().Error, e:
        msg = "Couldn't get object modification time from db (%d : %s)" % \
            (e.args[0], e.args[1])
        raise VistrailsDBException(msg)
    return id

def setup_db_tables(db_connection, version=None, old_version=None):
    if version is None:
        version = currentVersion
    if old_version is None:
        old_version = version
    try:
        def execute_file(c, f):
            cmd = ""
#             auto_inc_str = 'auto_increment'
#             not_null_str = 'not null'
#             engine_str = 'engine=InnoDB;'
            for line in f:
#                 if line.find(auto_inc_str) > 0:
#                     num = line.find(auto_inc_str)
#                     line = line[:num] + line[num+len(auto_inc_str):]
#                 if line.find(not_null_str) > 0:
#                     num = line.find(not_null_str)
#                     line = line[:num] + line[num+len(not_null_str):]
                line = line.strip()
                if cmd or not line.startswith('--'):
                    cmd += line
                    ending = line
                else:
                    ending = None
                if ending and ending[-1] == ';':
                    # FIXME engine stuff switch for MySQLdb, sqlite3
                    cmd = cmd.rstrip()
#                     if cmd.endswith(engine_str):
#                         cmd = cmd[:-len(engine_str)] + ';'
                    print cmd
                    c.execute(cmd)
                    cmd = ""

        # delete tables
        c = db_connection.cursor()
        schemaDir = getVersionSchemaDir(old_version)
        f = open(os.path.join(schemaDir, 'vistrails_drop.sql'))
        execute_file(c, f)
#         db_script = f.read()
#         c.execute(db_script)
        c.close()
        f.close()

        # create tables        
        c = db_connection.cursor()
        schemaDir = getVersionSchemaDir(version)
        f = open(os.path.join(schemaDir, 'vistrails.sql'))
        execute_file(c, f)
#         db_script = f.read()
#         c.execute(db_script)
        f.close()
        c.close()
    except get_db_lib().Error, e:
        raise VistrailsDBException("unable to create tables: " + str(e))

##############################################################################
# General I/O

def open_from_xml(filename, type):
    if type == DBVistrail.vtType:
        return open_vistrail_from_xml(filename)
    elif type == DBWorkflow.vtType:
        return open_workflow_from_xml(filename)
    elif type == DBLog.vtType:
        return open_log_from_xml(filename)
    elif type == DBRegistry.vtType:
        return open_registry_from_xml(filename)
    else:
        raise VistrailsDBException("cannot open object of type "
                                   "'%s' from xml" % type)

def save_to_xml(obj, filename, version=None):
    if obj.vtType == DBVistrail.vtType:
        return save_vistrail_to_xml(obj, filename, version)
    elif obj.vtType == DBWorkflow.vtType:
        return save_workflow_to_xml(obj, filename, version)
    elif obj.vtType == DBLog.vtType:
        return save_log_to_xml(obj, filename, version)
    elif obj.vtType == DBRegistry.vtType:
        return save_registry_to_xml(obj, filename, version)
    elif obj.vtType == DBOpmGraph.vtType:
        return save_opm_to_xml(obj, filename, version)
    else:
        raise VistrailsDBException("cannot save object of type "
                                   "'%s' to xml" % type)

def open_bundle_from_zip_xml(bundle_type, filename):
    if bundle_type == DBVistrail.vtType:
        return open_vistrail_bundle_from_zip_xml(filename)
    else:
        raise VistrailsDBException("cannot open bundle of type '%s' from zip" %\
                                       bundle_type)

def save_bundle_to_zip_xml(save_bundle, filename, tmp_dir=None, version=None):
    bundle_type = save_bundle.bundle_type
    if bundle_type == DBVistrail.vtType:
        return save_vistrail_bundle_to_zip_xml(save_bundle, filename, tmp_dir, version)
    elif bundle_type == DBLog.vtType:
        return save_log_bundle_to_xml(save_bundle, filename, version)
    elif bundle_type == DBWorkflow.vtType:
        return save_workflow_bundle_to_xml(save_bundle, filename, version)
    elif bundle_type == DBRegistry.vtType:
        return save_registry_bundle_to_xml(save_bundle, filename, version)
    else:
        raise VistrailsDBException("cannot save bundle of type '%s' to zip" % \
                                       bundle_type)

def open_bundle_from_db(bundle_type, connection, primary_obj_id, tmp_dir=None):
    if bundle_type == DBVistrail.vtType:
        return open_vistrail_bundle_from_db(connection, primary_obj_id, tmp_dir)
    else:
        raise VistrailsDBException("cannot open bundle of type '%s' from db" %\
                                       bundle_type)

def save_bundle_to_db(save_bundle, connection, do_copy=False, version=None):
    bundle_type = save_bundle.bundle_type
    if bundle_type == DBVistrail.vtType:
        return save_vistrail_bundle_to_db(save_bundle, connection, do_copy, version)
    elif bundle_type == DBLog.vtType:
        return save_log_bundle_to_db(save_bundle, connection, do_copy, version)
    elif bundle_type == DBWorkflow.vtType:
        return save_workflow_bundle_to_db(save_bundle, connection, do_copy, version)
    elif bundle_type == DBRegistry.vtType:
        return save_registry_bundle_to_db(save_bundle, connection, do_copy, version)
    else:
        raise VistrailsDBException("cannot save bundle of type '%s' to db" % \
                                       bundle_type)

def open_from_db(db_connection, type, obj_id):
    if type == DBVistrail.vtType:
        return open_vistrail_from_db(db_connection, obj_id)
    elif type == DBWorkflow.vtType:
        return open_workflow_from_db(db_connection, obj_id)
    elif type == DBLog.vtType:
        return open_log_from_db(db_connection, obj_id)
    elif type == DBRegistry.vtType:
        return open_registry_from_db(db_connection, obj_id)
    else:
        raise VistrailsDBException("cannot open object of type '%s' from db" % \
                                       type)

def save_to_db(obj, db_connection, do_copy=False):
    if obj.vtType == DBVistrail.vtType:
        return save_vistrail_to_db(obj, db_connection, do_copy)
    elif obj.vtType == DBWorkflow.vtType:
        return save_workflow_to_db(obj, db_connection, do_copy)
    elif obj.vtType == DBLog.vtType:
        return save_log_to_db(obj, db_connection, do_copy)
    elif obj.vtType == DBRegistry.vtType:
        return save_registry_to_db(obj, db_connection, do_copy)
    else:
        raise VistrailsDBException("cannot save object of type '%s' to db" % \
                                       type)

def delete_from_db(db_connection, type, obj_id):
    if type in [DBVistrail.vtType, DBWorkflow.vtType, DBLog.vtType,
                DBRegistry.vtType]:
        return delete_entity_from_db(db_connection, type, obj_id)

def close_zip_xml(temp_dir):
    """close_zip_xml(temp_dir: string) -> None
    Removes any temporary files for a vistrails file

    temp_dir: directory storing any persistent files
    """
    if temp_dir is None:
        return
    if not os.path.isdir(temp_dir):
        if os.path.isfile(temp_dir):
            os.remove(temp_dir)

        # cleanup has already happened
        return
    try:
        for root, dirs, files in os.walk(temp_dir, topdown=False):
            for name in files:
                os.remove(os.path.join(root, name))
            for name in dirs:
                os.rmdir(os.path.join(root, name))
        os.rmdir(temp_dir)
    except OSError, e:
        raise VistrailsDBException("Can't remove %s: %s" % (temp_dir, str(e)))

def serialize(object):
    daoList = getVersionDAO(currentVersion)
    return daoList.serialize(object)

def unserialize(str, obj_type):
    daoList = getVersionDAO(currentVersion)
    return daoList.unserialize(str, obj_type)
 
##############################################################################
# Vistrail I/O

def open_vistrail_from_xml(filename):
    """open_vistrail_from_xml(filename) -> Vistrail"""
    tree = ElementTree.parse(filename)
    version = get_version_for_xml(tree.getroot())
    try:
        daoList = getVersionDAO(version)
        vistrail = daoList.open_from_xml(filename, DBVistrail.vtType, tree)
        vistrail = translate_vistrail(vistrail, version)
        db.services.vistrail.update_id_scope(vistrail)
    except VistrailsDBException, e:
        msg = "This vistrail was created by a newer version of VisTrails "
        msg += "and cannot be opened."
        raise VistrailsDBException(msg)
    return vistrail

def open_vistrail_bundle_from_zip_xml(filename):
    """open_vistrail_bundle_from_zip_xml(filename) -> SaveBundle
    Open a vistrail from a zip compressed format.
    It expects that the vistrail file inside archive has name 'vistrail',
    the log inside archive has name 'log',
    abstractions inside archive have prefix 'abstraction_',
    and thumbnails inside archive are '.png' files in 'thumbs' dir

    """

    core.requirements.require_executable('unzip')

    vt_save_dir = tempfile.mkdtemp(prefix='vt_save')
    output = []
    cmdline = ['unzip', '-q','-o','-d', vt_save_dir, filename]
    result = execute_cmdline(cmdline, output)
    
    if result != 0 and len(output) != 0:
        raise VistrailsDBException("Unzip of '%s' failed" % filename)

    vistrail = None
    log = None
    log_fname = None
    abstraction_files = []
    unknown_files = []
    thumbnail_files = []
    try:
        for root, dirs, files in os.walk(vt_save_dir):
            for fname in files:
                if fname == 'vistrail' and root == vt_save_dir:
                    vistrail = open_vistrail_from_xml(os.path.join(root, fname))
                elif fname == 'log' and root == vt_save_dir:
                    # FIXME read log to get execution info
                    # right now, just ignore the file
                    log = None 
                    log_fname = os.path.join(root, fname)
                    # log = open_log_from_xml(os.path.join(root, fname))
                    # objs.append(DBLog.vtType, log)
                elif fname.startswith('abstraction_'):
                    abstraction_file = os.path.join(root, fname)
                    abstraction_files.append(abstraction_file)
                elif (fname.endswith('.png') and 
                      root == os.path.join(vt_save_dir,'thumbs')):
                    thumbnail_file = os.path.join(root, fname)
                    thumbnail_files.append(thumbnail_file)
                else:
                    unknown_files.append(os.path.join(root, fname))
    except OSError, e:
        raise VistrailsDBException("Error when reading vt file")
    if len(unknown_files) > 0:
        raise VistrailsDBException("Unknown files in vt file: %s" % \
                                       unknown_files)
    if vistrail is None:
        raise VistrailsDBException("vt file does not contain vistrail")
    vistrail.db_log_filename = log_fname

    save_bundle = SaveBundle(DBVistrail.vtType, vistrail, log, abstractions=abstraction_files, thumbnails=thumbnail_files)
    return (save_bundle, vt_save_dir)

def open_vistrail_bundle_from_db(db_connection, vistrail_id, tmp_dir=None):
    """open_vistrail_bundle_from_db(db_connection, id: long, tmp_dir: str) -> SaveBundle
       Open a vistrail bundle from the database.

    """
    vistrail = open_vistrail_from_db(db_connection, vistrail_id)
    # FIXME open log from db
    log = None
    # FIXME open abstractions from db
    abstractions = []
    thumbnails = open_thumbnails_from_db(db_connection, DBVistrail.vtType, vistrail_id, tmp_dir)
    return SaveBundle(DBVistrail.vtType, vistrail, log, abstractions=abstractions, thumbnails=thumbnails)

def open_vistrail_from_db(db_connection, id, lock=False, version=None):
    """open_vistrail_from_db(db_connection, id : long, lock: bool, 
                             version: str) 
         -> DBVistrail 

    """
    if db_connection is None:
        msg = "Need to call open_db_connection() before reading"
        raise VistrailsDBException(msg)
    if version is None:
        version = get_db_object_version(db_connection, id, DBVistrail.vtType)
    dao_list = getVersionDAO(version)
    vistrail = \
        dao_list.open_from_db(db_connection, DBVistrail.vtType, id, lock)
    vistrail = translate_vistrail(vistrail, version)
    for db_action in vistrail.db_get_actions():
        db_action.db_operations.sort(key=lambda x: x.db_id)
    db.services.vistrail.update_id_scope(vistrail)
    return vistrail

def save_vistrail_to_xml(vistrail, filename, version=None):
    tags = {'xmlns:xsi': 'http://www.w3.org/2001/XMLSchema-instance',
            'xsi:schemaLocation': 'http://www.vistrails.org/vistrail.xsd'
            }
    if version is None:
        version = currentVersion
    if not vistrail.db_version:
        vistrail.db_version = currentVersion

    # current_action holds the current action id 
    # (used by the controller--write_vistrail)
    current_action = 0L
    if hasattr(vistrail, 'db_currentVersion'):
        current_action = vistrail.db_currentVersion

    vistrail = translate_vistrail(vistrail, vistrail.db_version, version)

    daoList = getVersionDAO(version)        
    daoList.save_to_xml(vistrail, filename, tags, version)
    vistrail = translate_vistrail(vistrail, version)
    vistrail.db_currentVersion = current_action
    return vistrail

def save_vistrail_bundle_to_zip_xml(save_bundle, filename, vt_save_dir=None, version=None):
    """save_vistrail_bundle_to_zip_xml(save_bundle: SaveBundle, filename: str,
                                vt_save_dir: str, version: str)
         -> (save_bundle: SaveBundle, vt_save_dir: str)

    save_bundle: a SaveBundle object containing vistrail data to save
    filename: filename to save to
    vt_save_dir: directory storing any previous files

    Generates a zip compressed version of vistrail.
    It raises an Exception if there was an error.
    
    """

    core.requirements.require_executable('zip')

    if save_bundle.vistrail is None:
        raise VistrailsDBException('save_vistrail_bundle_to_zip_xml failed, '
                                   'bundle does not contain a vistrail')
    if not vt_save_dir:
        vt_save_dir = tempfile.mkdtemp(prefix='vt_save')
    # saving zip files flat so we'll do without this dir for now
    # abstraction_dir = os.path.join(vt_save_dir, 'abstractions')
    thumbnail_dir = os.path.join(vt_save_dir, 'thumbs')

    # Save Vistrail
    xml_fname = os.path.join(vt_save_dir, 'vistrail')
    save_vistrail_to_xml(save_bundle.vistrail, xml_fname, version)

    # Save Log
    if save_bundle.vistrail.db_log_filename is not None:
        xml_fname = os.path.join(vt_save_dir, 'log')
        if save_bundle.vistrail.db_log_filename != xml_fname:
            shutil.copyfile(save_bundle.vistrail.db_log_filename, xml_fname)
            save_bundle.vistrail.db_log_filename = xml_fname

    if save_bundle.log is not None:
        xml_fname = os.path.join(vt_save_dir, 'log')
        save_log_to_xml(save_bundle.log, xml_fname, version, True)
        save_bundle.vistrail.db_log_filename = xml_fname

    # Save Abstractions
    saved_abstractions = []
    for obj in save_bundle.abstractions:
        if type(obj) == type(""):
            # FIXME we should have an abstraction directory here instead
            # of the abstraction_ prefix...
            if not os.path.basename(obj).startswith('abstraction_'):
                obj_fname = 'abstraction_' + os.path.basename(obj)
            else:
                obj_fname = os.path.basename(obj)
            # xml_fname = os.path.join(abstraction_dir, obj_fname)
            xml_fname = os.path.join(vt_save_dir, obj_fname)
            saved_abstractions.append(xml_fname)
            # if not os.path.exists(abstraction_dir):
            #     os.mkdir(abstraction_dir)
            # print "obj:", obj
            # print "xml_fname:", xml_fname
            if obj != xml_fname:
                # print 'copying %s -> %s' % (obj, xml_fname)
                try:
                    shutil.copyfile(obj, xml_fname)
                except Exception, e:
                    saved_abstractions.pop()
                    debug.critical('copying %s -> %s failed: %s' % \
                                       (obj, xml_fname, str(e)))
        else:
            raise VistrailsDBException('save_vistrail_bundle_to_zip_xml failed, '
                                       'abstraction list entry must be a filename')
    # Save Thumbnails
    saved_thumbnails = []
    for obj in save_bundle.thumbnails:
        if type(obj) == type(""):
            obj_fname = os.path.basename(obj)
            png_fname = os.path.join(thumbnail_dir, obj_fname)
            saved_thumbnails.append(png_fname)
            if not os.path.exists(thumbnail_dir):
                os.mkdir(thumbnail_dir)
            
            #print 'copying %s -> %s' %(obj, png_fname)
            try:
                shutil.copyfile(obj, png_fname)
            except Exception, e:
                saved_thumbnails.pop()
                debug.warning('copying thumbnail %s -> %s failed: %s' % \
                              (obj, png_fname, str(e))) 
        else:
            raise VistrailsDBException('save_vistrail_bundle_to_zip_xml failed, '
                                       'thumbnail list entry must be a filename')

    tmp_zip_dir = tempfile.mkdtemp(prefix='vt_zip')
    tmp_zip_file = os.path.join(tmp_zip_dir, "vt.zip")
    output = []
    rel_vt_save_dir = os.path.split(vt_save_dir)[1]
    cur_dir = os.getcwd()
    # on windows, we assume zip.exe is in the current directory when
    # running from the binary install
    zipcmd = 'zip'
    if systemType in ['Windows', 'Microsoft']:
        zipcmd = os.path.join(cur_dir,'zip.exe')
        if not os.path.exists(zipcmd):
            zipcmd = 'zip.exe' #assume zip is in path
    cmdline = [zipcmd, '-r', '-q', tmp_zip_file, '.']
    try:
        #if we want that directories are also stored in the zip file
        # we need to run from the vt directory
        os.chdir(vt_save_dir)
        result = execute_cmdline(cmdline,output)
        os.chdir(cur_dir)
        #print result, output
        if result != 0 or len(output) != 0:
            for line in output:
                if line.find('deflated') == -1:
                    raise VistrailsDBException(" ".join(output))
        shutil.copyfile(tmp_zip_file, filename)
    finally:
        os.unlink(tmp_zip_file)
        os.rmdir(tmp_zip_dir)
    save_bundle = SaveBundle(save_bundle.bundle_type, save_bundle.vistrail, save_bundle.log, thumbnails=saved_thumbnails, abstractions=saved_abstractions)
    return (save_bundle, vt_save_dir)

def save_vistrail_bundle_to_db(save_bundle, db_connection, do_copy=False, version=None):
    if save_bundle.vistrail is None:
        raise VistrailsDBException('save_vistrail_bundle_to_db failed, '
                                   'bundle does not contain a vistrail')
    vistrail = save_vistrail_to_db(save_bundle.vistrail, db_connection, do_copy, version)
    log = None
    if save_bundle.vistrail.db_log_filename is not None:
        if save_bundle.log is not None:
            log = merge_logs(save_bundle.log,
                             save_bundle.vistrail.db_log_filename)
        else:
            log = open_log_from_xml(save_bundle.vistrail.db_log_filename, True)
    elif save_bundle.log is not None:
        log = save_bundle.log
    if log is not None:
        # Set foreign key 'vistrail_id' for the log to point at its vistrail
        log.db_vistrail_id = vistrail.db_id
        log = save_log_to_db(log, db_connection, do_copy, version)
    # FIXME Save abstractions to the db
    save_thumbnails_to_db(save_bundle.thumbnails, db_connection)
    return SaveBundle(DBVistrail.vtType, vistrail, log, abstractions=list(save_bundle.abstractions), thumbnails=list(save_bundle.thumbnails))

def save_vistrail_to_db(vistrail, db_connection, do_copy=False, version=None):
    if db_connection is None:
        msg = "Need to call open_db_connection() before reading"
        raise VistrailsDBException(msg)
    if version is None:
        version = get_db_version(db_connection)
        if version is None:
            version = currentVersion
    if not vistrail.db_version:
        vistrail.db_version = currentVersion

    dao_list = getVersionDAO(version)

    # db_connection.begin()
    
    # current_action holds the current action id 
    # (used by the controller--write_vistrail)
    current_action = 0L
    if hasattr(vistrail, 'db_currentVersion'):
        current_action = vistrail.db_currentVersion

    if not do_copy and vistrail.db_last_modified is not None:
        new_time = get_db_object_modification_time(db_connection, 
                                                   vistrail.db_id,
                                                   DBVistrail.vtType)
        if new_time > vistrail.db_last_modified:
            # need synchronization
            old_vistrail = open_vistrail_from_db(db_connection, 
                                                 vistrail.db_id,
                                                 True, version)
            old_vistrail = translate_vistrail(old_vistrail, version)
            # the "old" one is modified and changes integrated
            current_action = \
                db.services.vistrail.synchronize(old_vistrail, vistrail, 
                                                 current_action)
            vistrail = old_vistrail
    vistrail.db_last_modified = get_current_time(db_connection)

    vistrail = translate_vistrail(vistrail, vistrail.db_version, version)
    dao_list.save_to_db(db_connection, vistrail, do_copy)
    db_connection.commit()
    vistrail = translate_vistrail(vistrail, version)
    vistrail.db_currentVersion = current_action
    return vistrail

##############################################################################
# Workflow I/O

def open_workflow_from_xml(filename):
    """open_workflow_from_xml(filename) -> DBWorkflow"""
    tree = ElementTree.parse(filename)
    version = get_version_for_xml(tree.getroot())
    daoList = getVersionDAO(version)
    workflow = daoList.open_from_xml(filename, DBWorkflow.vtType, tree)
    workflow = translate_workflow(workflow, version)
    db.services.workflow.update_id_scope(workflow)
    return workflow

def open_workflow_from_db(db_connection, id, lock=False, version=None):
    """open_workflow_from_db(db_connection, id : long: lock: bool, 
                             version: str) 
         -> DBWorkflow 
    
    """
    if db_connection is None:
        msg = "Need to call open_db_connection() before reading"
        raise VistrailsDBException(msg)
    if version is None:
        version = get_db_object_version(db_connection, id, DBWorkflow.vtType)
    dao_list = getVersionDAO(version)
    workflow = \
        dao_list.open_from_db(db_connection, DBWorkflow.vtType, id, lock)
    workflow = translate_workflow(workflow, version)
    return workflow
    
def save_workflow_to_xml(workflow, filename, version=None):
    tags = {'xmlns:xsi': 'http://www.w3.org/2001/XMLSchema-instance',
            'xsi:schemaLocation': 'http://www.vistrails.org/workflow.xsd'
            }
    if version is None:
        version = currentVersion
    if not workflow.db_version:
        workflow.db_version = currentVersion
    workflow = translate_workflow(workflow, workflow.db_version, version)

    daoList = getVersionDAO(version)
    daoList.save_to_xml(workflow, filename, tags, version)
    workflow = translate_workflow(workflow, version)
    return workflow

def save_workflow_bundle_to_xml(save_bundle, filename, version=None):
    if save_bundle.workflow is None:
        raise VistrailsDBException('save_workflow_bundle_to_xml failed, '
                                   'bundle does not contain a workflow')
    workflow = save_workflow_to_xml(save_bundle.workflow, filename, version)
    return SaveBundle(DBWorkflow.vtType, workflow=workflow)

def save_workflow_to_db(workflow, db_connection, do_copy=False, version=None):
    if db_connection is None:
        msg = "Need to call open_db_connection() before reading"
        raise VistrailsDBException(msg)
    if version is None:
        version = get_db_version(db_connection)
        if version is None:
            version = currentVersion
    if not workflow.db_version:
        workflow.db_version = currentVersion
    workflow = translate_workflow(workflow, workflow.db_version, version)
    dao_list = getVersionDAO(version)

    db_connection.begin()
    workflow.db_last_modified = get_current_time(db_connection)
    dao_list.save_to_db(db_connection, workflow, do_copy)
    db_connection.commit()
    workflow = translate_workflow(workflow, version)
    return workflow

def save_workflow_bundle_to_db(save_bundle, db_connection, do_copy=False, 
                               version=None):
    if save_bundle.workflow is None:
        raise VistrailsDBException('save_workflow_bundle_to_db failed, '
                                   'bundle does not contain a workflow')
    workflow = save_workflow_to_db(save_bundle.workflow, db_connection, do_copy, 
                                   version)
    return SaveBundle(DBWorkflow.vtType, workflow=workflow)

##############################################################################
# Logging I/O

def open_log_from_xml(filename, was_appended=False):
    """open_log_from_xml(filename) -> DBLog"""
    if was_appended:
        parser = ElementTree.XMLTreeBuilder()
        parser.feed("<log>\n")
        f = open(filename, "rb")
        parser.feed(f.read())
        parser.feed("</log>\n")
        root = parser.close()
        workflow_execs = []
        for node in root:
            version = get_version_for_xml(node)
            daoList = getVersionDAO(version)
            workflow_exec = \
                daoList.read_xml_object(DBWorkflowExec.vtType, node)
            if version != currentVersion:
                # if version is wrong, dump this into a dummy log object, 
                # then translate, then get workflow_exec back
                log = DBLog()
                translate_log(log, currentVersion, version)
                log.db_add_workflow_exec(workflow_exec)
                log = translate_log(log, version)
                workflow_exec = log.db_workflow_execs[0]
            workflow_execs.append(workflow_exec)
        log = DBLog(workflow_execs=workflow_execs)
        db.services.log.update_ids(log)
    else:
        tree = ElementTree.parse(filename)
        version = get_version_for_xml(tree.getroot())
        daoList = getVersionDAO(version)
        log = daoList.open_from_xml(filename, DBLog.vtType, tree)
        log = translate_log(log, version)
        db.services.log.update_id_scope(log)
    return log

def open_log_from_db(db_connection, id, lock=False, version=None):
    """open_log_from_db(db_connection, id : long: lock: bool, version: str) 
         -> DBLog 
    
    """
    if db_connection is None:
        msg = "Need to call open_db_connection() before reading"
        raise VistrailsDBException(msg)
    if version is None:
        version = get_db_object_version(db_connection, id, DBLog.vtType)
    dao_list = getVersionDAO(version)
    log = dao_list.open_from_db(db_connection, DBLog.vtType, id, lock)
    log = translate_log(log, version)
    return log

def save_log_to_xml(log, filename, version=None, do_append=False):
    if version is None:
        version = currentVersion
    if not log.db_version:
        log.db_version = currentVersion
    log = translate_log(log, log.db_version, version)

    daoList = getVersionDAO(version)
    if do_append:
        log_file = open(filename, 'ab')
        for workflow_exec in log.workflow_execs:
            # cannot do correct numbering here...
            # but need to save so that we can use it for deletes
            wf_exec_id = workflow_exec.db_id
            workflow_exec.db_id = -1L
            daoList.save_to_xml(workflow_exec, log_file, {}, version)
            workflow_exec.db_id = wf_exec_id
        log_file.close()
    else:
        tags = {'xmlns:xsi': 'http://www.w3.org/2001/XMLSchema-instance',
                'xsi:schemaLocation': 'http://www.vistrails.org/log.xsd'
                }
        daoList.save_to_xml(log, filename, tags, version)
    log = translate_log(log, version)
    return log

def save_log_bundle_to_xml(save_bundle, filename, version=None):
    if save_bundle.log is None:
        raise VistrailsDBException('save_log_bundle_to_xml failed, '
                                   'bundle does not contain a log')
        
    log = save_log_to_xml(save_bundle.log, filename, version)
    return SaveBundle(DBLog.vtType, log=log)

def save_log_to_db(log, db_connection, do_copy=False, version=None):
    if db_connection is None:
        msg = "Need to call open_db_connection() before reading"
        raise VistrailsDBException(msg)
    if version is None:
        version = get_db_version(db_connection)
        if version is None:
            version = currentVersion
    if not log.db_version:
        log.db_version = currentVersion
    log = translate_log(log, log.db_version, version)
    dao_list = getVersionDAO(version)

    db_connection.begin()
    log.db_last_modified = get_current_time(db_connection)
    dao_list.save_to_db(db_connection, log, do_copy)
    db_connection.commit()
    log = translate_log(log, version)
    return log

def save_log_bundle_to_db(save_bundle, db_connection, do_copy=False, 
                          version=None):
    if save_bundle.log is None:
        raise VistrailsDBException('save_log_bundle_to_db failed, '
                                   'bundle does not contain a log')
        
    log = save_log_to_db(save_bundle.log, db_connection, do_copy, version)
    return SaveBundle(DBLog.vtType, log=log)

def merge_logs(new_log, vt_log_fname):
    log = open_log_from_xml(vt_log_fname, True)
    for workflow_exec in new_log.db_workflow_execs:
        workflow_exec.db_id = log.id_scope.getNewId(DBWorkflowExec.vtType)
        log.db_add_workflow_exec(workflow_exec)
    return log

##############################################################################
# OPM I/O

def save_opm_to_xml(opm_graph, filename, version=None):    
    # FIXME, we're using workflow, version, and log here...
    # which aren't in DBOpmGraph...
    if version is None:
        version = currentVersion
    daoList = getVersionDAO(version)
    tags = {'xmlns': 'http://openprovenance.org/model/v1.01.a',
            }
    opm_graph = db.services.opm.create_opm(opm_graph.workflow, 
                                           opm_graph.version,
                                           opm_graph.log,
                                           opm_graph.registry)
    daoList.save_to_xml(opm_graph, filename, tags, version)
    return opm_graph

##############################################################################
# Registry I/O

def open_registry_from_xml(filename):
    tree = ElementTree.parse(filename)
    version = get_version_for_xml(tree.getroot())
    daoList = getVersionDAO(version)
    registry = daoList.open_from_xml(filename, DBRegistry.vtType, tree)
    registry = translate_registry(registry, version)
    db.services.registry.update_id_scope(registry)
    return registry

def open_registry_from_db(db_connection, id, lock=False, version=None):
    """open_registry_from_db(db_connection, id : long: lock: bool, 
                             version: str) -> DBRegistry 
    
    """
    if db_connection is None:
        msg = "Need to call open_db_connection() before reading"
        raise VistrailsDBException(msg)
    if version is None:
        version = get_db_object_version(db_connection, id, DBRegistry.vtType)
    dao_list = getVersionDAO(version)
    registry = dao_list.open_from_db(db_connection, DBRegistry.vtType, id, lock)
    registry = translate_registry(registry, version)
    return registry

def save_registry_to_xml(registry, filename, version=None):
    tags = {'xmlns:xsi': 'http://www.w3.org/2001/XMLSchema-instance',
            'xsi:schemaLocation': 'http://www.vistrails.org/registry.xsd'
            }
    if version is None:
        version = currentVersion
    if not registry.db_version:
        registry.db_version = currentVersion
    registry = translate_registry(registry, registry.db_version, version)

    daoList = getVersionDAO(version)
    daoList.save_to_xml(registry, filename, tags, version)
    registry = translate_registry(registry, version)
    return registry

def save_registry_bundle_to_xml(save_bundle, filename, version=None):
    if save_bundle.registry is None:
        raise VistrailsDBException('save_registry_bundle_to_xml failed, '
                                   'bundle does not contain a registry')
        
    registry = save_registry_to_xml(save_bundle.registry, filename, version)
    return SaveBundle(DBRegistry.vtType, registry=registry)

def save_registry_to_db(registry, db_connection, do_copy=False, version=None):
    if db_connection is None:
        msg = "Need to call open_db_connection() before reading"
        raise VistrailsDBException(msg)
    if version is None:
        version = get_db_version(db_connection)
        if version is None:
            version = currentVersion
    if not registry.db_version:
        registry.db_version = currentVersion
    registry = translate_registry(registry, registry.db_version, version)
    dao_list = getVersionDAO(version)

    db_connection.begin()
    registry.db_last_modified = get_current_time(db_connection)
    dao_list.save_to_db(db_connection, registry, do_copy)
    db_connection.commit()
    registry = translate_registry(registry, version)
    return registry

def save_registry_bundle_to_db(save_bundle, db_connection, do_copy=False, 
                               version=None):
    if save_bundle.registry is None:
        raise VistrailsDBException('save_registry_bundle_to_db failed, '
                                   'bundle does not contain a registry')
        
    registry = save_registry_to_db(save_bundle.registry, db_connection, do_copy, 
                                   version)
    return SaveBundle(DBRegistry.vtType, registry=registry)

##############################################################################
# Abstraction I/O

def open_abstraction_from_db(db_connection, id, lock=False):
    """open_abstraction_from_db(db_connection, id : long: lock: bool) 
         -> DBAbstraction 
    
    """
    if db_connection is None:
        msg = "Need to call open_db_connection() before reading"
        raise VistrailsDBException(msg)
    abstraction = read_sql_objects(db_connection, DBAbstraction.vtType, 
                                   id, lock)[0]

    # not sure where this really should be done...
    # problem is that db reads the add ops, then change ops, then delete ops
    # need them ordered by their id
    for db_action in abstraction.db_get_actions():
        db_action.db_operations.sort(key=lambda x: x.db_id)
    db.services.abstraction.update_id_scope(abstraction)
    return abstraction

def save_abstraction_to_db(abstraction, db_connection, do_copy=False):
    db_connection.begin()
    if abstraction.db_last_modified is None:
        do_copy = True
    if not do_copy:
        match_id = get_matching_abstraction_id(db_connection, abstraction)
        # FIXME remove print
        print 'match_id:', match_id
        if match_id is not None:
            abstraction.db_id = match_id
            abstraction.is_new = False
        else:
            do_copy = True
        new_time = get_db_object_modification_time(db_connection, 
                                                   abstraction.db_id,
                                                   DBAbstraction.vtType)
        if new_time > abstraction.db_last_modified:
            # need synchronization
            # FIXME remove print
            print '*** doing synchronization ***'
            old_abstraction = open_abstraction_from_db(db_connection, 
                                                       abstraction.db_id,
                                                       True)
            # the "old" one is modified and changes integrated
            db.services.vistrail.synchronize(old_abstraction, abstraction,
                                             0L)
            abstraction = old_abstraction
    if do_copy:
        abstraction.db_id = None
    abstraction.db_last_modified = get_current_time(db_connection)
    write_sql_objects(db_connection, [abstraction], do_copy)
    db_connection.commit()
    return abstraction

##############################################################################
# Thumbnail I/O

def open_thumbnails_from_db(db_connection, obj_type, obj_id, tmp_dir=None):
    """open_thumbnails_from_db(db_connection, obj_type: DB*,
                            obj_id: long, tmp_dir: str) -> [str]

    Gets a list of all thumbnails associated with this object from the
    annotations table in the db (by comparing obj_type with the column
    'entity_type' and obj_id with the column 'entity_id') and for any
    thumbnails not found in tmp_dir, they are retreived from the db and
    saved into tmp_dir.
    Returns a list of absolute file paths for all thumbnails associated
    with this object that exist in tmp_dir after the function has run.

    """
    if db_connection is None:
        msg = "Need to call open_db_connection() before reading"
        raise VistrailsDBException(msg)
    if tmp_dir is None:
        return []

    # First get associated file names from annotation table
    prepared_statement = format_prepared_statement(
    """
    SELECT a.value
    FROM annotation a
    WHERE a.akey = '__thumb__' AND a.entity_id = ? AND a.entity_type = ?
    """)
    try:
        c = db_connection.cursor()
        c.execute(prepared_statement, (obj_id, obj_type))
        file_names = [file_name for (file_name,) in c.fetchall()]
        c.close()
    except get_db_lib().Error, e:
        msg = "Couldn't get thumbnails list from db (%d : %s)" % \
            (e.args[0], e.args[1])
        raise VistrailsDBException(msg)

    # Next get all thumbnails from the db that aren't already in tmp_dir
    get_db_file_names = [fname for fname in file_names if fname not in os.listdir(tmp_dir)]
    for file_name in get_db_file_names:
        prepared_statement = format_prepared_statement(
        """
        SELECT t.image_bytes
        FROM thumbnail t
        WHERE t.file_name = ?
        """)
        try:
            c = db_connection.cursor()
            c.execute(prepared_statement, (file_name,))
            row = c.fetchone()
            c.close()
        except get_db_lib().Error, e:
            msg = "Couldn't get thumbnail from db (%d : %s)" % \
                (e.args[0], e.args[1])
            raise VistrailsDBException(msg)
        if row is not None:
            image_bytes = row[0]
            try:
                absfname = os.path.join(tmp_dir, file_name)
                image_file = open(absfname, 'wb')
                image_file.write(image_bytes)
                image_file.close()
            except IOError, e:
                msg = "Couldn't write thumbnail file to disk: %s" % absfname
                raise VistrailsDBException(msg)
        else:
            debug.warning("db: Referenced thumbnail not found locally or in the database: '%s'" % file_name)
    # Return only thumbnails that now exist locally
    return [os.path.join(tmp_dir, file_name) for file_name in file_names if file_name in os.listdir(tmp_dir)]

def save_thumbnails_to_db(absfnames, db_connection):
    """save_thumbnails_to_db(absfnames: list, db_connection) -> None
    Saves all thumbnails from a list of local absolute file paths into the db,
    except those already present on the db.

    """
    if db_connection is None:
        msg = "Need to call open_db_connection() before reading"
        raise VistrailsDBException(msg)
    if absfnames is None or len(absfnames) == 0:
        return None

    # Determine which thumbnails already exist in db
    statement = """
    SELECT t.file_name
    FROM thumbnail t
    WHERE t.file_name IN %s
    """
    check_file_names = [os.path.basename(absfname).replace("'", "''").replace("\\", "\\\\") for absfname in absfnames]
    # SQL syntax needs SOMETHING if list is empty - use filename that's illegal on all platforms
    check_file_names.append(':/')
    sql_in_token = str(tuple(check_file_names))
    try:
        c = db_connection.cursor()
        c.execute(statement % sql_in_token)
        db_file_names = [file_name for (file_name,) in c.fetchall()]
        c.close()
    except get_db_lib().Error, e:
        msg = "Couldn't check which thumbnails already exist in db (%d : %s)" % \
            (e.args[0], e.args[1])
        raise VistrailsDBException(msg)
    insert_absfnames = [absfname for absfname in absfnames if os.path.basename(absfname) not in db_file_names]

    # Save any thumbnails that don't already exist in db
    prepared_statement = format_prepared_statement(
    """
    INSERT INTO thumbnail(file_name, image_bytes, last_modified)
    VALUES (?, ?, ?)
    """)
    try:
        c = db_connection.cursor()
        for absfname in insert_absfnames:
            image_file = open(absfname, 'rb')
            image_bytes = image_file.read()
            image_file.close()
            c.execute(prepared_statement, (os.path.basename(absfname), image_bytes, get_current_time(db_connection).strftime('%Y-%m-%d %H:%M:%S')))
            db_connection.commit()
        c.close()
    except IOError, e:
        msg = "Couldn't read thumbnail file for writing to db: %s" % absfname
        raise VistrailsDBException(msg)
    except get_db_lib().Error, e:
        msg = "Couldn't insert thumbnail into db (%d : %s)" % \
            (e.args[0], e.args[1])
        raise VistrailsDBException(msg)
    return None

##############################################################################
# I/O Utilities

def delete_entity_from_db(db_connection, type, obj_id):
    if db_connection is None:
        msg = "Need to call open_db_connection() before reading"
        raise VistrailsDBException(msg)
    version = get_db_version(db_connection)
    if version is None:
        version = currentVersion
    dao_list = getVersionDAO(version)
    dao_list.delete_from_db(db_connection, type, obj_id)
    db_connection.commit()
    
def get_version_for_xml(root):
    version = root.get('version', None)
    if version is not None:
        return version
    msg = "Cannot find version information"
    raise VistrailsDBException(msg)

def get_type_for_xml(root):
    return root.tag

def get_current_time(db_connection=None):
    timestamp = datetime.now()
    if db_connection is not None:
        try:
            c = db_connection.cursor()
            # FIXME MySQL versus sqlite3
            c.execute("SELECT NOW();")
            # c.execute("SELECT DATETIME('NOW');")
            row = c.fetchone()
            if row:
                # FIXME MySQL versus sqlite3
                timestamp = row[0]
                # timestamp = datetime.strptime(row[0], '%Y-%m-%d %H:%M:%S')
            c.close()
        except get_db_lib().Error, e:
            debug.critical("Logger Error %d: %s" % (e.args[0], e.args[1]))

    return timestamp

def create_temp_folder(prefix='vt_save'):
    return tempfile.mkdtemp(prefix=prefix)

def remove_temp_folder(temp_dir):
    if temp_dir is None:
        return
    if not os.path.isdir(temp_dir):
        if os.path.isfile(temp_dir):
            os.remove(temp_dir)

        # cleanup has already happened
        return
    try:
        for root, dirs, files in os.walk(temp_dir, topdown=False):
            for name in files:
                os.remove(os.path.join(root, name))
            for name in dirs:
                os.rmdir(os.path.join(root, name))
        os.rmdir(temp_dir)
    except OSError, e:
        raise VistrailsDBException("Can't remove %s: %s" % (temp_dir, str(e)))
    
##############################################################################
# Testing

import unittest
import core.system
import os

class TestDBIO(unittest.TestCase):
    def test1(self):
        """test importing an xml file"""

        vistrail = open_vistrail_from_xml( \
            os.path.join(core.system.vistrails_root_directory(),
                         'tests/resources/dummy.xml'))
        assert vistrail is not None
        
    def test2(self):
        """test importing an xml file"""

        vistrail = open_vistrail_from_xml( \
            os.path.join(core.system.vistrails_root_directory(),
                         'tests/resources/dummy_new.xml'))
        assert vistrail is not None

    def test3(self):
        """test importing a vt file"""

        # FIXME include abstractions
        (save_bundle, vt_save_dir) = open_bundle_from_zip_xml( \
            DBVistrail.vtType,
            os.path.join(core.system.vistrails_root_directory(),
                         'tests/resources/dummy_new.vt'))
        assert save_bundle.vistrail is not None

    def test4(self):
        """ test saving a vt file """

        # FIXME include abstractions
        filename = os.path.join(core.system.vistrails_root_directory(),
                                'tests/resources/dummy_new_temp.vt')
    
        (save_bundle, vt_save_dir) = open_bundle_from_zip_xml( \
            DBVistrail.vtType,
            os.path.join(core.system.vistrails_root_directory(),
                         'tests/resources/dummy_new.vt'))
        try:
            save_bundle_to_zip_xml(save_bundle, filename, vt_save_dir)
            if os.path.isfile(filename):
                os.unlink(filename)
        except Exception, e:
            self.fail(str(e))

