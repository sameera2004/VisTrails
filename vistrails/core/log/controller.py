############################################################################
##
## Copyright (C) 2006-2007 University of Utah. All rights reserved.
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

from core.log.workflow_exec import WorkflowExec
from core.log.module_exec import ModuleExec
from core.log.loop_exec import LoopExec
from core.log.machine import Machine
from core.vistrail.annotation import Annotation
from core.vistrail.pipeline import Pipeline
from core.vistrail.vistrail import Vistrail
import core.system

class DummyLogController(object):
    """DummyLogger is a class that has the entire interface for a logger
    but simply ignores the calls."""
    def start_workflow_execution(*args, **kwargs):
        pass
    def finish_workflow_execution(*args, **kwargs):
        pass
    def start_module_execution(*args, **kwargs):
        pass
    def finish_module_execution(*args, **kwargs):
        pass
    def start_loop_execution(*args, **kwargs):
        pass
    def finish_loop_execution(*args, **kwargs):
        pass
    def insert_module_annotations(*args, **kwargs):
        pass

class LogController(object):
    def __init__(self, log):
        self.log = log
        self.workflow_exec = None
        self.machine = None

    def start_workflow_execution(self, vistrail=None, pipeline=None, 
                                 currentVersion=None):
        self.machine = Machine(id=-1,
                               name=core.system.current_machine(),
                               os=core.system.systemType,
                               architecture=core.system.current_architecture(),
                               processor=core.system.current_processor(),
                               ram=core.system.guess_total_memory())
        
        to_add = True
        for machine in self.log.machine_list:
            if self.machine.equals_no_id(machine):
                to_add = False
                self.machine = machine
        if to_add:
            self.machine.id = self.log.id_scope.getNewId(Machine.vtType)
            self.log.add_machine(self.machine)

        if vistrail is not None:
            parent_type = Vistrail.vtType
            parent_id = vistrail.id
        else:
            parent_type = Pipeline.vtType
            parent_id = pipeline.id

        wf_exec_id = self.log.id_scope.getNewId(WorkflowExec.vtType)
        if vistrail is not None:
            session = vistrail.current_session
        else:
            session = None
        self.workflow_exec = WorkflowExec(id=wf_exec_id,
                                          user=core.system.current_user(),
                                          ip=core.system.current_ip(),
                                          vt_version= \
                                              core.system.vistrails_version(),
                                          ts_start=core.system.current_time(),
                                          parent_type=parent_type,
                                          parent_id=parent_id,
                                          parent_version=currentVersion,
                                          completed=0,
                                          session=session)
        self.log.add_workflow_exec(self.workflow_exec)

    def finish_workflow_execution(self, errors):
        self.workflow_exec.ts_end = core.system.current_time()
        if len(errors) > 0:
            self.workflow_exec.completed = -1
        else:
            self.workflow_exec.completed = 1

    def start_module_execution(self, module, module_id, module_name, 
                               abstraction_id=None, abstraction_version=None, 
                               cached=0):
        if (module.is_fold_operator) and (not module.first_iteration):
            self.start_loop_execution(module)
        else:
            m_exec_id = self.log.id_scope.getNewId(ModuleExec.vtType)
            module_exec = ModuleExec(id=m_exec_id,
                                     machine_id=self.machine.id,
                                     module_id=module_id,
                                     module_name=module_name,
                                     abstraction_id=abstraction_id,
                                     abstraction_version=abstraction_version,
                                     cached=cached,
                                     ts_start=core.system.current_time(),
                                     completed=0)
            module.module_exec = module_exec
            self.workflow_exec.add_module_exec(module_exec)
            if (module.is_fold_operator):
                self.start_loop_execution(module)

    def finish_module_execution(self, module, error=''):
        if (module.is_fold_operator) and (not module.last_iteration) and (not error):
            self.finish_loop_execution(module, error)
        else:
            if (module.is_fold_operator):
                self.finish_loop_execution(module, error)
                if error:
                    error = 'Error in loop execution with id %d'%module.module_exec.\
                            loop_execs[-1].id
            module.module_exec.ts_end = core.system.current_time()
            if not error:
                module.module_exec.completed = 1
            else:
                module.module_exec.completed = -1
                module.module_exec.error = error
            del module.module_exec

    def start_loop_execution(self, module):
        l_exec_id = self.log.id_scope.getNewId(LoopExec.vtType)
        loop_exec = LoopExec(id = l_exec_id,
                             ts_start = core.system.current_time(),
                             input = module.element)
        module.module_exec.add_loop_exec(loop_exec)

    def finish_loop_execution(self, module, error):
        module.module_exec.loop_execs[-1].ts_end = core.system.current_time()
        if not error:
            module.module_exec.loop_execs[-1].completed = 1
        else:
            module.module_exec.loop_execs[-1].completed = -1
            module.module_exec.loop_execs[-1].error = error

    def insert_module_annotations(self, module, a_dict):
        for k,v in a_dict.iteritems():
            a_id = self.log.id_scope.getNewId(Annotation.vtType)
            annotation = Annotation(id=a_id,
                                    key=k,
                                    value=v)
            module.module_exec.add_annotation(annotation)
            
