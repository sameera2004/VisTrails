from core.modules.vistrails_module import Module, ModuleError
from Matrix import *
from Array import *
import scipy
from scipy import io, sparse


class ArrayUtilityModule(object):
    my_namespace = 'scipy|matrix|utilities|Matlab'

class MatlabReader(ArrayUtilityModule, Module):
    """ Read a Matlab .mat file into a SciPy matrix """
    # Gather inputs here
    def get_inputs(self):
        if self.has_input("Filename"):
            self.fname = self.get_input("Filename")
        else:
            self.fname = self.get_input("File").name

    # Set required members externally.  This is just a helper function!
    def set_member(self, name, val):
        setattr(self, name, val)

    # This is the work that the compute() method does
    def process_compute(self):
        m = io.loadmat(self.fname, None, 0)
        vals = m.values()

        for t in vals:
            if type(t) == numpy.ndarray:
                if t.dtype == 'object':
                    continue
                mat = t

        return (mat,)

    # Take the returns from the processing and put them out on the outputs.
    def set_outputs(self, results):
        try:
            out = Matrix()
            out.set_matrix(sparse.csc_matrix(results[0]))
            
            self.set_output("Matrix Output", out)
        except:
            pass
        
        out_ar = NDArray()
        out_ar.set_array(numpy.array(results[0]))
        self.set_output("Array Output", out_ar)

    # The compute method for vistrails compatibility
    def compute(self):
        self.get_inputs()            
        results = self.process_compute()
        self.set_outputs(results)
        
    @classmethod
    def register(cls, reg, basic):
        reg.add_module(cls, namespace=cls.my_namespace)
        reg.add_input_port(cls, "Filename", (basic.String, 'Filename'))
        reg.add_input_port(cls, "File", (basic.File, 'File'))
        reg.add_output_port(cls, "Matrix Output", (Matrix, 'Matrix Output'))
        reg.add_output_port(cls, "Array Output", (NDArray, 'Array Output'))
    
class MatlabWriter(ArrayUtilityModule, Module):
    """ Write a Matlab .mat file from a SciPy matrix """
    def compute(self):
        if self.has_input("Filename"):
            fname = self.get_input("Filename")
        else:
            fname = self.get_input("File").name

        ar_list = self.get_input_list("Arrays")
        mat_list = self.get_input_list("Matrices")
        ar_dict = {}
        for i in xrange(len(ar_list)):
            ar_name = "array_" + str(i)
            ar_dict[ar_name] = ar_list[i].get_array()

        for i in xrange(len(mat_list)):
            mat_name = "matrix_" + str(i)
            ar_dict[mat_name] = mat_list[i].get_matrix()

        io.savemat(fname, ar_dict)

    @classmethod
    def register(cls, reg, basic):
        reg.add_module(cls, namespace=cls.my_namespace)
        reg.add_input_port(cls, "Filename", (basic.String, 'Filename'))
        reg.add_input_port(cls, "File", (basic.File, 'File'))
        reg.add_input_port(cls, "Arrays", (NDArray, 'Arrays to Save'))
        reg.add_input_port(cls, "Matrices", (Matrix, 'Matrices to Save'))
            
