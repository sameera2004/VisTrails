#############################################################################
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
## of VisTrails), please contact us at contact@vistrails.org.
##
## This file is provided AS IS with NO WARRANTY OF ANY KIND, INCLUDING THE
## WARRANTY OF DESIGN, MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE.
##
############################################################################
import itk
import core.modules
from core.modules.vistrails_module import Module, ModuleError
from ITK import *
from Image import Image

class RegionOfInterestImageFilter(Module):
    my_namespace="Filter|Selection"

    def setStart(self, start):
        if start == 2:
            self.index = self.get_input("Input 2D Index").ind_
        else:
            self.index = self.get_input("Input 3D Index").ind_

        self.region_.SetIndex(self.index)

    def compute(self):
        im = self.get_input("Input Image")

        #check for input PixelType
        if self.has_input("Input PixelType"):
            inPixelType = self.get_input("Input PixelType")
        else:
            inPixelType = im.getPixelType()

        #check for output PixelType
        if self.has_input("Output PixelType"):
            outPixelType = self.get_input("Output PixelType")
        else:
            outPixelType = inPixelType

        #check for dimension
        if self.has_input("Input Dimension"):
            dim = self.get_input("Input Dimension")
        else:
            dim = im.getDim()

        if self.has_input("Output Dimension"):
            outDim = self.get_input("Output Dimension")
        else:
            outDim = dim

        #set up filter
        inImgType = itk.Image[inPixelType._type, dim]
        outImgType = itk.Image[outPixelType._type, outDim]

        self.filter_ = itk.RegionOfInterestImageFilter[inImgType, outImgType].New()

        #TODO this is not correct, needs fixing
        if self.has_input("Input Region"):
            self.region_ = self.get_input("Input Region").region_
        else:
            self.region_ = itk.ImageRegion[indim]()
            self.setStart(indim)
            self.region_.SetSize(self.get_input("Region Size").size_)

        self.filter_.SetRegionOfInterest(self.region_)
        self.filter_.SetInput(im.getImg())
        self.filter_.Update()

        #setup output image
        outIm = Image()
        outIm.setImg(self.filter_.GetOutput())
        outIm.setPixelType(outPixelType)
        outIm.setDim(outDim)

        self.set_output("Output Image", outIm)
        self.set_output("Output PixelType", outPixelType)
        self.set_output("Output Dimension", outDim)
        self.set_output("Filter", self)

    @classmethod
    def register(cls, reg, basic):
        reg.add_module(cls, name="Region of Interest Image Filter", namespace=cls.my_namespace)

        reg.add_input_port(cls, "Input Image", (Image, 'Input Image'))
        reg.add_input_port(cls, "Input Dimension", (basic.Integer, 'Dimension'),True)
        reg.add_input_port(cls, "Output Dimension", (basic.Integer, 'Dimension'),True)
        reg.add_input_port(cls, "Input PixelType", (PixelType, 'Input PixelType'),True)
        reg.add_input_port(cls, "Output PixelType", (PixelType, 'Output PixelType'),True)
        reg.add_input_port(cls, "Input Region", (Region, 'Input Region'))
        reg.add_input_port(cls, "Region Size", (Size, 'Region Size'))

        reg.add_output_port(cls, "Output Image", (Image, 'Output Image'))
        reg.add_output_port(cls, "Output PixelType", (PixelType, 'Output PixelType'),True)
        reg.add_output_port(cls, "Output Dimension", (basic.Integer, 'Dimension'),True)

class CastImageFilter(Module):
    my_namespace="Filter|Selection"
    def compute(self):
        im = self.get_input("Input Image")

        #check for input PixelType
        if self.has_input("Input PixelType"):
            inPixelType = self.get_input("Input PixelType")
        else:
            inPixelType = im.getPixelType()

        #check for output PixelType
        if self.has_input("Output PixelType"):
            outPixelType = self.get_input("Output PixelType")
        else:
            outPixelType = inPixelType

        #check for in dimension
        if self.has_input("Input Dimension"):
            dim = self.get_input("Input Dimension")
        else:
            dim = im.getDim()

        #check for out dimension
        if self.has_input("Output Dimension"):
            outDim = self.get_input("Output Dimension")
        else:
            outDim = dim

        #set up filter
        inImgType = itk.Image[inPixelType._type, dim]
        outImgType = itk.Image[outPixelType._type, outDim]

        self.filter_ = itk.CastImageFilter[inImgType, outImgType].New(im.getImg())
        self.filter_.Update()

        #setup output image
        outIm = Image()
        outIm.setImg(self.filter_.GetOutput())
        outIm.setPixelType(outPixelType)
        outIm.setDim(outDim)
        
        self.set_output("Output Image", outIm)
        self.set_output("Output PixelType", outPixelType)
        self.set_output("Output Dimension", outDim)
        self.set_output("Filter", self)

    @classmethod
    def register(cls, reg, basic):
        reg.add_module(cls, name="Cast Image Filter", namespace=cls.my_namespace)

        reg.add_input_port(cls, "Input Dimension", (basic.Integer, 'Input Dimension'),True)
        reg.add_input_port(cls, "Output Dimension", (basic.Integer, 'Output Dimension'))
        reg.add_input_port(cls, "Input PixelType", (PixelType, 'Input PixelType'),True)
        reg.add_input_port(cls, "Output PixelType", (PixelType, 'Output PixelType'))
        reg.add_input_port(cls, "Input Image", (Image, 'Input Image'))

        reg.add_output_port(cls, "Output Image", (Image, 'Output Image'))
        reg.add_output_port(cls, "Output PixelType", (PixelType, 'Output PixelType'),True)
        reg.add_output_port(cls, "Filter", (Filter, 'Filter'),True)
        reg.add_output_port(cls, "Output Dimension", (basic.Integer, 'Output Dimension'),True)


class ExtractImageFilter(Module):
    my_namespace="Filter|Selection"
    def compute(self):
        #TODO should this be Input Volume?
        im = self.get_input("Input Volume")
        #check for input PixelType
        if self.has_input("Input PixelType"):
            inPixelType = self.get_input("Input PixelType")
        else:
            inPixelType = im.getPixelType()

        #set outPixelType
        outPixelType = inPixelType

        #check for dimension
        if self.has_input("Dimension"):
            dim = self.get_input("Dimension")
        else:
            dim = im.getDim()
            
        #check for out dimension
        if self.has_input("Output Dimension"):
            outDim = self.get_input("Output Dimension")
        else:
            outDim = im.getDim()

        #set up filter
        inImgType = itk.Image[inPixelType._type, dim]
        outImgType = itk.Image[outPixelType._type, outDim]

        self.filter_ = itk.ExtractImageFilter[inImgType,outImgType].New(im.getImg())

        region = self.get_input("Extraction Region")
        self.filter_.SetExtractionRegion(region.region_)
        self.filter_.Update()

        #setup output image
        outIm = Image()
        outIm.setImg(self.filter_.GetOutput())
        outIm.setPixelType(outPixelType)
        outIm.setDim(outDim)

        self.set_output("Output Image", outIm)
        self.set_output("Output PixelType", outPixelType)
        self.set_output("Dimension", outDim)

    @classmethod
    def register(cls, reg, basic):
        reg.add_module(cls, name="Extract Image Filter", namespace=cls.my_namespace)

        reg.add_input_port(cls, "Input Volume", (Image, 'Input Image'))
        reg.add_input_port(cls, "Input Dimension", (basic.Integer, 'Input Dimension'),True)
        reg.add_input_port(cls, "Output Dimension", (basic.Integer, 'Output Dimension'),True)
        reg.add_input_port(cls, "Input PixelType", (PixelType, 'Input PixelType'),True)
        reg.add_input_port(cls, "Extraction Region", (Region, 'Extraction Region'))

        reg.add_output_port(cls, "Output Image", (Image, 'Output Image'))
        reg.add_output_port(cls, "Output PixelType", (PixelType, 'Output PixelType'),True)
        reg.add_output_port(cls, "Dimension", (basic.Integer, 'Dimension'),True)
