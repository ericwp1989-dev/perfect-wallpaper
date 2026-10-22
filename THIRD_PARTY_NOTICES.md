# Third party notices

Perfect Wallpaper is MIT licensed (see LICENSE). The Windows download bundles the
software below, each under its own license.

## Bundled in PerfectWallpaper.exe

| Component | License | Source |
|---|---|---|
| realesrgan-ncnn-vulkan (the fallback AI engine) | MIT | https://github.com/xinntao/Real-ESRGAN-ncnn-vulkan |
| ncnn, and its Python package (runs the AI models) | BSD 3 clause | https://github.com/Tencent/ncnn |
| Real-ESRGAN models (realesrgan-x4plus-anime, RealESRGAN General x4 v3) | BSD 3 clause | https://github.com/xinntao/Real-ESRGAN |
| Nomos8kSC and LSDIRplusC models, by Helaman (Philip Hofmann) | CC BY 4.0 | https://github.com/Phhofm/models |
| The three models above, converted to the ncnn format | made from the authors' original files by scripts/convert_models.py (a change of file format only; same licenses) | this repository |
| YuNet face detection model, by Shiqi Yu | MIT | https://github.com/opencv/opencv_zoo |
| pillow-heif (iPhone photos), with libheif and libde265 | BSD 3 clause; libheif and libde265 are LGPL 3.0, included as separate libraries | https://github.com/bigcat88/pillow_heif |
| Microsoft OpenMP runtime (vcomp140.dll, shipped with the engine) | Visual C++ Redistributable terms | https://learn.microsoft.com/cpp/windows/redistributing-visual-cpp-files |
| Python | PSF License | https://www.python.org |
| Tcl/Tk | Tcl/Tk License (BSD style) | https://www.tcl.tk |
| NumPy | BSD 3 clause | https://numpy.org |
| OpenCV (opencv-python) | Apache 2.0 | https://github.com/opencv/opencv-python |
| Pillow | MIT-CMU | https://python-pillow.org |
| tkinterdnd2 and tkdnd | MIT; tkdnd is BSD style | https://github.com/pmgagne/tkinterdnd2 |
| PyInstaller bootloader | GPL 2.0 with an exception that allows bundled apps under any license | https://pyinstaller.org |

## Downloaded later, only if you set up the stronger AI

These are not part of the download. The program fetches them on request into your
user folder.

| Component | License | Source |
|---|---|---|
| Python (embeddable package) | PSF License | https://www.python.org |
| PyTorch | BSD 3 clause | https://pytorch.org |
| diffusers, transformers, accelerate, huggingface_hub, safetensors | Apache 2.0 | https://github.com/huggingface |
| Stable Diffusion 1.5 | CreativeML OpenRAIL-M | https://huggingface.co/stable-diffusion-v1-5/stable-diffusion-v1-5 |
| ControlNet 1.1 tile model, by Lvmin Zhang | OpenRAIL | https://huggingface.co/lllyasviel/control_v11f1e_sd15_tile |

The OpenRAIL licenses allow free use but forbid some harmful uses; see their pages.

## Real-ESRGAN

```
BSD 3-Clause License

Copyright (c) 2021, Xintao Wang
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

1. Redistributions of source code must retain the above copyright notice, this
   list of conditions and the following disclaimer.

2. Redistributions in binary form must reproduce the above copyright notice,
   this list of conditions and the following disclaimer in the documentation
   and/or other materials provided with the distribution.

3. Neither the name of the copyright holder nor the names of its
   contributors may be used to endorse or promote products derived from
   this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
```

## Real-ESRGAN-ncnn-vulkan

```
The MIT License (MIT)

Copyright (c) 2021 Xintao Wang

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

------------------------
The following is the License of realsr-ncnn-vulkan

The MIT License (MIT)

Copyright (c) 2019 nihui

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## ncnn

```
Tencent is pleased to support the open source community by making ncnn available.
Copyright (C) 2017 Tencent. All rights reserved.

The ncnn binary is licensed under the BSD 3-Clause License. Parts of the ncnn
source (neon_mathfun.h, sse_mathfun.h, avx_mathfun.h) are under the zlib License.
Full text: https://github.com/Tencent/ncnn/blob/master/LICENSE.txt
```
