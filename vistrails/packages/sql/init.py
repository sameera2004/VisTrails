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

from core.bundles import py_import

MySQLdb = py_import('MySQLdb', {'linux-ubuntu':'python-mysqldb',
                                'linux-fedora':'MySQL-python'})

psycopg2 = py_import('psycopg2', {'linux-ubuntu':'python-psycopg2',
                                  'linux-fedora':'python-psycopg2'})
from PyQt4 import QtCore, QtGui
import urllib

from core.modules.vistrails_module import Module, ModuleError, NotCacheable
from core.modules.source_configure import SourceConfigurationWidget
from core.utils import PortAlreadyExists
from gui.theme import CurrentTheme

class QPasswordEntry(QtGui.QDialog):
    def __init__(self, parent=None):
        QtGui.QWidget.__init__(self, parent)
        self.setModal(True)
        self.setWindowTitle("Enter Password:")
        self.setLayout(QtGui.QVBoxLayout())
        hbox = QtGui.QHBoxLayout()
        hbox.addWidget(QtGui.QLabel("Password:"))
        self.line_edit = QtGui.QLineEdit()
        self.line_edit.setEchoMode(QtGui.QLineEdit.Password)
        hbox.addWidget(self.line_edit)
        self.layout().addLayout(hbox)

        bbox = QtGui.QHBoxLayout()
        cancel = QtGui.QPushButton("Cancel")
        ok = QtGui.QPushButton("OK")
        ok.setDefault(True)
        bbox.addWidget(cancel, 1, QtCore.Qt.AlignRight)
        bbox.addWidget(ok, 0, QtCore.Qt.AlignRight)
        self.layout().addLayout(bbox)
        self.connect(ok, QtCore.SIGNAL("clicked(bool)"), self.accept)
        self.connect(cancel, QtCore.SIGNAL("clicked(bool)"), self.reject)

    def get_password(self):
        return str(self.line_edit.text())

class DBConnection(Module):
    def __init__(self):
         Module.__init__(self)
         self.conn = None
         self.protocol = 'mysql'
    
    def get_db_lib(self):
        if self.protocol == 'mysql':
            return MySQLdb
        elif self.protocol == 'postgresql':
            return psycopg2
        else:
            raise ModuleError(self, "Currently no support for '%s'" % protocol)
        
    def ping(self):
        """ping() -> boolean 
        It will ping the database to check if the connection is alive.
        It returns True if it is, False otherwise. 
        This can be used for preventing the "MySQL Server has gone away" error. 
        """
        result = False
        if self.conn:
            try:
                self.conn.ping()
                result = True
            except self.get_db_lib().OperationalError, e:
                result = False
            except AttributeError, e:
                #psycopg2 connections don't have a ping method
                try:
                    if self.conn.status == 1:
                        result = True
                except Exception, e:
                    result = False
        return result
    
    def open(self):        
        retry = True
        while retry:
            config = {'host': self.host,
                      'port': self.port,
                      'user': self.user}
            
            # unfortunately keywords are not standard across libraries
            if self.protocol == 'mysql':    
                config['db'] = self.db_name
                if self.password is not None:
                    config['passwd'] = self.password
            elif self.protocol == 'postgresql':
                config['database'] = self.db_name
                if self.password is not None:
                    config['password'] = self.password
            try:
                self.conn = self.get_db_lib().connect(**config)
                break
            except self.get_db_lib().Error, e:
                print str(e)
                if (e[0] == 1045 or self.get_db_lib().OperationalError 
                    and self.password is None):
                    passwd_dlg = QPasswordEntry()
                    if passwd_dlg.exec_():
                        self.password = passwd_dlg.get_password()
                    else:
                        retry = False
                else:
                    raise ModuleError(self, str(e))
             
    def compute(self):
        self.checkInputPort('db_name')
        self.host = self.forceGetInputFromPort('host', 'localhost')
        self.port = self.forceGetInputFromPort('port', 3306)
        self.user = self.forceGetInputFromPort('user', None)
        self.db_name = self.getInputFromPort('db_name')
        self.protocol = self.forceGetInputFromPort('protocol', 'mysql')
        if self.hasInputFromPort('password'):
            self.password = self.getInputFromPort('password')
        else:
            self.password = None

        self.open()

    # nice to have enumeration constant type
    _input_ports = [('host', '(edu.utah.sci.vistrails.basic:String)'),
                    ('port', '(edu.utah.sci.vistrails.basic:Integer)'),
                    ('user', '(edu.utah.sci.vistrails.basic:String)'),
                    ('db_name', '(edu.utah.sci.vistrails.basic:String)'),
                    ('protocol', '(edu.utah.sci.vistrails.basic:String)')]
    _output_ports = [('self', '(edu.utah.sci.vistrails.sql:DBConnection)')]

class SQLSource(Module):
    def __init__(self):
        Module.__init__(self)
        self.is_cacheable = self.cachedOff
        
    def compute(self):
        cached = False
        if self.hasInputFromPort('cacheResults'):
            cached = self.getInputFromPort('cacheResults')
        self.checkInputPort('connection')
        connection = self.getInputFromPort('connection')
        inputs = [self.getInputFromPort(k) for k in self.inputPorts
                  if k != 'source' and k != 'connection' and k!= 'cacheResults']
        print 'inputs:', inputs
        s = urllib.unquote(str(self.forceGetInputFromPort('source', '')))
        if not connection.ping():
            connection.open()
        cur = connection.conn.cursor()
        cur.execute(s, inputs)
    
        if cached:
            self.is_cacheable = self.cachedOn
        else:
            self.is_cacheable = self.cachedOff
            
        self.setResult('resultSet', cur.fetchall())

    def cachedOn(self):
        return True
    
    def cachedOff(self):
        return False
    
    _input_ports = [('connection', \
                         '(edu.utah.sci.vistrails.sql:DBConnection)'),
                    ('cacheResults', \
                      '(edu.utah.sci.vistrails.basic:Boolean)'),    
                    ('source', '(edu.utah.sci.vistrails.basic:String)')]
    _output_ports = \
        [('resultSet', '(edu.utah.sci.vistrails.control_flow:ListOfElements)')]

class SQLSourceConfigurationWidget(SourceConfigurationWidget):
    def __init__(self, module, controller, parent=None):
        SourceConfigurationWidget.__init__(self, module, controller, None,
                                           True, False, parent)
        
_modules = [DBConnection,
            (SQLSource, {'configureWidgetType': SQLSourceConfigurationWidget})]