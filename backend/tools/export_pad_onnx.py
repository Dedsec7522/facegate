"""Export the MiniFASNet anti-spoofing checkpoints (Apache-2.0, minivision-ai) to ONNX.

The network definition below is FaceGate's own re-implementation of the published MiniFASNet
architecture (MobileFaceNet-style depth-wise blocks with optional squeeze-excitation), written so the
vendor's state_dict keys load unchanged. torch is only needed for this one-off export; FaceGate's
runtime uses the produced ONNX files via ONNX Runtime.

    tools/.venv-export/Scripts/python tools/export_pad_onnx.py
"""
from __future__ import annotations

from pathlib import Path

import torch
from torch import nn

MODELS = Path(__file__).resolve().parent.parent / "models"

# Channel plans ("keep" lists) published with the checkpoints.
KEEP_V1 = [32, 32, 103, 103, 64, 13, 13, 64, 26, 26, 64, 13, 13, 64, 52, 52, 64, 231, 231, 128,
           154, 154, 128, 52, 52, 128, 26, 26, 128, 52, 52, 128, 26, 26, 128, 26, 26, 128, 308, 308,
           128, 26, 26, 128, 26, 26, 128, 512, 512]
KEEP_V2 = [32, 32, 103, 103, 64, 13, 13, 64, 13, 13, 64, 13, 13, 64, 13, 13, 64, 231, 231, 128,
           231, 231, 128, 52, 52, 128, 26, 26, 128, 77, 77, 128, 26, 26, 128, 26, 26, 128, 308, 308,
           128, 26, 26, 128, 26, 26, 128, 512, 512]


class ConvBlock(nn.Module):
    def __init__(self, cin, cout, k=(1, 1), s=(1, 1), p=(0, 0), groups=1):
        super().__init__()
        self.conv = nn.Conv2d(cin, cout, k, s, p, groups=groups, bias=False)
        self.bn = nn.BatchNorm2d(cout)
        self.prelu = nn.PReLU(cout)

    def forward(self, x):
        return self.prelu(self.bn(self.conv(x)))


class LinearBlock(nn.Module):
    def __init__(self, cin, cout, k=(1, 1), s=(1, 1), p=(0, 0), groups=1):
        super().__init__()
        self.conv = nn.Conv2d(cin, cout, k, s, p, groups=groups, bias=False)
        self.bn = nn.BatchNorm2d(cout)

    def forward(self, x):
        return self.bn(self.conv(x))


class SE(nn.Module):
    def __init__(self, ch, r):
        super().__init__()
        self.avg_pool = nn.AdaptiveAvgPool2d(1)
        self.fc1 = nn.Conv2d(ch, ch // r, 1, bias=False)
        self.bn1 = nn.BatchNorm2d(ch // r)
        self.relu = nn.ReLU(inplace=True)
        self.fc2 = nn.Conv2d(ch // r, ch, 1, bias=False)
        self.bn2 = nn.BatchNorm2d(ch)
        self.sigmoid = nn.Sigmoid()

    def forward(self, x):
        w = self.sigmoid(self.bn2(self.fc2(self.relu(self.bn1(self.fc1(self.avg_pool(x)))))))
        return x * w


class DepthWise(nn.Module):
    def __init__(self, c1, c2, c3, residual=False, k=(3, 3), s=(2, 2), p=(1, 1), se=False, se_r=4):
        super().__init__()
        self.conv = ConvBlock(c1[0], c1[1])
        self.conv_dw = ConvBlock(c2[0], c2[1], k, s, p, groups=c2[0])
        self.project = LinearBlock(c3[0], c3[1])
        self.residual = residual
        if se:
            self.se_module = SE(c3[1], se_r)
        self.se = se

    def forward(self, x):
        y = self.project(self.conv_dw(self.conv(x)))
        if self.residual:
            if self.se:
                y = self.se_module(y)
            return x + y
        return y


class Stage(nn.Module):
    """A run of residual depth-wise blocks; the last one carries SE in the SE variant."""

    def __init__(self, keep, start, n, se):
        super().__init__()
        blocks = []
        for i in range(n):
            b = start + 3 * i
            c1, c2, c3 = (keep[b], keep[b + 1]), (keep[b + 1], keep[b + 2]), (keep[b + 2], keep[b + 3])
            blocks.append(DepthWise(c1, c2, c3, residual=True, s=(1, 1), se=(se and i == n - 1)))
        self.model = nn.Sequential(*blocks)

    def forward(self, x):
        return self.model(x)


class MiniFASNet(nn.Module):
    def __init__(self, keep, se=False, conv6_kernel=(5, 5), embedding_size=128, num_classes=3):
        super().__init__()
        self.embedding_size = embedding_size
        self.conv1 = ConvBlock(3, keep[0], (3, 3), (2, 2), (1, 1))
        self.conv2_dw = ConvBlock(keep[0], keep[1], (3, 3), (1, 1), (1, 1), groups=keep[1])
        self.conv_23 = DepthWise((keep[1], keep[2]), (keep[2], keep[3]), (keep[3], keep[4]))
        self.conv_3 = Stage(keep, 4, 4, se)
        self.conv_34 = DepthWise((keep[16], keep[17]), (keep[17], keep[18]), (keep[18], keep[19]))
        self.conv_4 = Stage(keep, 19, 6, se)
        self.conv_45 = DepthWise((keep[37], keep[38]), (keep[38], keep[39]), (keep[39], keep[40]))
        self.conv_5 = Stage(keep, 40, 2, se)
        self.conv_6_sep = ConvBlock(keep[46], keep[47])
        self.conv_6_dw = LinearBlock(keep[47], keep[48], conv6_kernel, groups=keep[48])
        self.linear = nn.Linear(512, embedding_size, bias=False)
        self.bn = nn.BatchNorm1d(embedding_size)
        self.drop = nn.Dropout(0.0)
        self.prob = nn.Linear(embedding_size, num_classes, bias=False)

    def forward(self, x):
        for m in (self.conv1, self.conv2_dw, self.conv_23, self.conv_3, self.conv_34, self.conv_4, self.conv_45,
                  self.conv_5, self.conv_6_sep, self.conv_6_dw):
            x = m(x)
        x = x.flatten(1)
        if self.embedding_size != 512:
            x = self.linear(x)
        return self.prob(self.drop(self.bn(x)))


EXPORTS = [
    ("4_0_0_80x80_MiniFASNetV1SE.pth", KEEP_V1, True, "minifasnet_v1se_4.0_80x80.onnx"),
    ("2.7_80x80_MiniFASNetV2.pth", KEEP_V2, False, "minifasnet_v2_2.7_80x80.onnx"),
]

for ckpt, keep, se, out in EXPORTS:
    model = MiniFASNet(keep, se=se)
    state = torch.load(MODELS / ckpt, map_location="cpu", weights_only=True)
    state = {(k[7:] if k.startswith("module.") else k): v for k, v in state.items()}
    missing, unexpected = model.load_state_dict(state, strict=True), None
    model.eval()
    dummy = torch.zeros(1, 3, 80, 80)
    torch.onnx.export(model, dummy, str(MODELS / out), input_names=["input"], output_names=["logits"],
                      dynamic_axes={"input": {0: "batch"}, "logits": {0: "batch"}}, opset_version=13, dynamo=False)
    with torch.no_grad():
        print(f"exported {out}  logits(zeros)={model(dummy)[0].numpy().round(3)}")
