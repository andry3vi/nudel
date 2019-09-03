#  SPDX-License-Identifier: GPL-3.0+
#
# Copyright © 2019 O. Papst.
#
# This file is part of pyENSDF.
#
# pyENSDF is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# pyENSDF is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with pyENSDF.  If not, see <http://www.gnu.org/licenses/>.

"""Python interface for ENSDF nuclear data"""

from __future__ import annotations

from datetime import datetime
import re
from typing import Union, List, Tuple, Optional

from scipy.constants import physical_constants

from .provider import ENSDFProvider, ENSDFFileProvider
from .util import nucid_from_az, az_from_nucid, Quantity

class ENSDF:
    def __init__(self, provider: ENSDFProvider = None) -> None:
        self.provider = provider or ENSDFFileProvider()
        self.datasets = dict()
        for k in self.provider.get_all_dataset_names():
            self.datasets[k] = None

    def get_dataset(self, nucleus: Tuple[int, Optional[int]], name: str) -> Dataset:
        if (nucleus, name) not in self.datasets:
            raise KeyError("Dataset not found")
        # TODO: activate cache
        if self.datasets[(nucleus, name)] is None or True:
            res = self.provider.get_dataset(nucleus, name)
            self.datasets[(nucleus, name)] = Dataset(self, res)
        return self.datasets[(nucleus, name)]
    
    def get_adopted_levels(self, nucleus: Tuple[int, int]) -> Dataset:
        # TODO: activate cache
        if (nucleus, "ADOPTED LEVELS") not in self.datasets or True:
            res = Dataset(self, self.provider.get_adopted_levels(nucleus))
            self.datasets[(nucleus, "ADOPTED LEVELS")] = res
        return self.datasets[(nucleus, "ADOPTED LEVELS")]

    def get_datasets_by_mass(self, mass: int) -> List[str]:
        return self.provider.get_datasets(mass)
 
    def get_datasets_by_nuclide(self, mass: str) -> List[str]:
        pass



class Dataset:
    def __init__(self, ensdf: ENSDF, dataset_plain: str):
        self.ensdf = ENSDF
        self.header, *self.raw = dataset_plain.split("\n")
        self.nucid = self.header[0:5].strip()
        self.dataset_id = self.header[9:39].strip()
        self.dataset_ref = self.header[39:65].strip()
        self.publication = self.header[65:74].strip()
        try:
            self.date = datetime.strptime(self.header[74:80].strip(), "%Y%m")
        except ValueError:
            self.date = None
        self.records = []
        self.levels = []
        self.history = {}
        self.qrecords = []
        self.comments = []
        self.parents = []
        self.references = []
        self.cross_references = []
        self._parse_dataset()

    def _add_record(self, record, comments, xref, level=None):
        try:
            rec_type = get_record_type(record)
            rec = rec_type(self, record, comments, xref, level)
        except:
            print(record)
            raise
        self.records.append(rec)
        return rec
    
    def _add_level(self, record, comments, xref):
        lvl = LevelRecord(self, record, comments, xref)
        self.levels.append(lvl)
        return lvl


    def _parse_dataset(self):
        comments = []
        record = []
        xref = []
        level = None
        history = ""
        header = True

        for line in self.raw[:-1]:
            if header:
                if line[6].upper() in ["C", "D","T"]:
                    self.comments.append(line)
                else:
                    if (line[7].lower() in "bagel" or
                        (line[7] in " D" and line[8] in "PAN")):
                        header = False
                    elif line[7] == "X":
                        self.cross_references.append(CrossReferenceRecord(self, line))
                    elif line[7] == "P":
                        self.parents.append(ParentRecord(self, line))
                    elif line[7] == "R":
                        self.references.append(ReferenceRecord(self, line))
                    elif line[7].upper() == "Q":
                        self.qrecords.append(QValueRecord(self, line))
                    elif line[7].upper() == "H":
                        history += line[9:80] + " "
                    elif line[7].upper() == "N":
                        pass # TODO: Normalization
            if header:
                continue

            try:
                if ((line[7].lower() in "bagel" or
                    (line[7] in " D" and line[8] in "PAN"))
                    and line[5:7] == "  "):
                    if record:
                        if record[0][7] == "L":
                            level = self._add_level(record, comments, xref)
                        else:
                            self._add_record(record, comments, xref, level)
                    comments = []
                    record = []
                    xref = []
                    record.append(line)
                elif line[5:7] == "X ":
                    xref.append(line)
                elif line[6] == " ":
                    record.append(line)
                elif line[5:7].lower() in [" c", " d", " t"]:
                    comments.append([line])
                elif line[6].lower() in "cdt":
                    comments[-1].append(line)
                else:
                    # This is a broken record
                    record.append(line)
            except (IndexError, ValueError):
                print(record)
                raise


            #if line[7].lower() in "bagel" and line[6].lower() not in "ct":
            #    if line[5] == " " and record:
            #        self._add_record(record, comments)
            #        comments = []
            #        record = []
            #    if line[6].lower() not in "ct":
            #        record.append(line)
            #if line[6].lower() not in "ct":
            #    comments.append(line)
        try:
            if record:
                if record[0][7] == "L":
                    level = self._add_level(record, comments, xref)
                else:
                    self._add_record(record, comments, xref, level)
        except (IndexError, ValueError):
            print(record)
            raise

        for entry in history.split("$")[:-1]:
            try:
                k, v = entry.split("=", maxsplit=1)
                self.history[k.strip()] = v.strip()
            except ValueError:
                # TODO: Maybe wrong linebreak?
                pass


class BaseRecord:
    pass


class Record(BaseRecord):
    def __init__(self, dataset, record, comments, xref):
        self.prop = dict()
        self.dataset = dataset
        self.comments = []
        self.xref = xref
        if comments:
            for comment in comments:
                self.comments.append(GeneralCommentRecord(dataset, comment))

    def load_prop(self, lines):
        for line in lines:
            for entry in line[9:].split("$"):
                entry = entry.strip()
                if not entry:
                    continue
                if "=" in entry:
                    quant, value = entry.split("=", maxsplit=1)
                    self.prop[quant.strip()] = value.strip()
                else:
                    for symb in ["<", ">"]:
                        if symb in entry:
                            quant, value = entry.split(symb, maxsplit=1)
                            self.prop[quant.strip()] = symb + value.strip()
                            return
                    for abbr in ["GT", "LT", "GE", "LE", "AP", "CA", "SY"]:
                        if f" {abbr} " in entry:
                            quant, quant, value = entry.split(" ", maxsplit=2)
                            self.prop[quant.strip()] = value.strip() + f" {quant}"
                            return
                    if entry[-1] == "?":
                        self.prop[entry[:-1]] = "?"
                        return
                    raise ValueError(f"Cannot process property: '{entry}'.")


class QValueRecord(BaseRecord):
    def __init__(self, dataset, line):
        self.q_beta_minus = (line[9:19].strip(), line[19:21].strip())
        self.neutron_separation = (line[21:29].strip(), line[29:31].strip())
        self.proton_separation = (line[31:39].strip(), line[39:41].strip())
        self.alpha_decay = (line[41:49].strip(), line[49:55].strip())
        self.q_ref = line[55:80].strip()


class CrossReferenceRecord(BaseRecord):
    def __init__(self, dataset, line):
        self.dataset = dataset
        self.dssym = line[8]
        self.dsid = line[9:39].strip()


class GeneralCommentRecord(BaseRecord):
    def __init__(self, dataset, comment):
        self.dataset = dataset
        self.comment = comment
        #self.continuation = line[5] not in ["1", " "]
        #self.comment_type = line[6]
        #self.rtype = line[7]
        #self.psym = line[8]
        #self.comment_text = line[9:80]


class ParentRecord(Record):
    def __init__(self, dataset, record):
        super().__init__(dataset, record, None, None)
        self.prop["E"] = record[0][9:19].strip()
        self.prop["DE"] = record[0][19:21].strip()
        self.prop["J"] = record[0][21:39].strip()
        self.prop["T"] = record[0][39:49].strip()
        self.prop["DT"] = record[0][49:55].strip()
        self.prop["QP"] = record[0][64:74].strip()
        self.prop["DQP"] = record[0][74:76].strip()
        self.prop["ION"] = record[0][76:80].strip()
        self.load_prop(record[1:])


class LevelRecord(Record):
    def __init__(self, dataset, record, comments, xref):
        super().__init__(dataset, record, comments, xref)
        self.prop["E"] = record[0][9:19].strip()
        self.prop["DE"] = record[0][19:21].strip()
        self.prop["J"] = record[0][21:39].strip()
        self.prop["T"] = record[0][39:49].strip()
        self.prop["DT"] = record[0][49:55].strip()
        self.prop["L"] = record[0][55:64].strip()
        self.prop["S"] = record[0][64:74].strip()
        self.prop["DS"] = record[0][74:76].strip()
        self.prop["C"] = record[0][76].strip()
        self.prop["MS"] = record[0][77:79].strip()
        self.prop["Q"] = record[0][79].strip()
        self.load_prop(record[1:])
        
        self.decays = []
        self.populating = []

        self.attrs = {}
        try:
            self.energy = Quantity(self.prop["E"], self.prop["DE"])
        except (IndexError, ValueError):
            print(self.prop["E"])
            print(self.prop["DE"])
            raise
        self.ang_mom = self.prop["J"]
        self.half_life = Quantity(self.prop["T"], self.prop["DT"])
        self.questionable = (self.prop["Q"] == "?")
        self.expected = (self.prop["Q"] == "S")
        self.metastable = (self.prop["MS"] and self.prop["MS"][0] == "M")
        self.spec_strength = Quantity(self.prop["S"], self.prop["DS"])


    def add_decay(self, decay):
        self.decays.append(decay)

class DecayRecord(Record):
    def __init__(self, dataset, record, comments, xref, dest_level):
        super().__init__(dataset, record, comments, xref)
        self.dest_level = dest_level

class BetaRecord(DecayRecord):
    def __init__(self, dataset, record, comments, xref, dest_level):
        super().__init__(dataset, record, comments, xref, dest_level)
        self.prop["E"] = record[0][9:19].strip()
        self.prop["DE"] = record[0][19:21].strip()
        self.prop["IB"] = record[0][21:29].strip()
        self.prop["DIB"] = record[0][29:31].strip()
        self.prop["LOGFT"] = record[0][41:49].strip()
        self.prop["DFT"] = record[0][49:55].strip()
        self.prop["C"] = record[0][76].strip()
        self.prop["UN"] = record[0][77:79].strip()
        self.prop["Q"] = record[0][79].strip()
        self.load_prop(record[1:])
        
        self.energy = Quantity(self.prop["E"], self.prop["DE"])
        self.questionable = (self.prop["Q"] == "?")
        self.expected = (self.prop["Q"] == "S")


class ECRecord(DecayRecord):
    def __init__(self, dataset, record, comments, xref, dest_level):
        super().__init__(dataset, record, comments, xref, dest_level)
        self.prop["E"] = record[0][9:19].strip()
        self.prop["DE"] = record[0][19:21].strip()
        self.prop["IB"] = record[0][21:29].strip()
        self.prop["DIB"] = record[0][29:31].strip()
        self.prop["IE"] = record[0][31:39].strip()
        self.prop["DIE"] = record[0][39:41].strip()
        self.prop["LOGFT"] = record[0][41:49].strip()
        self.prop["DFT"] = record[0][49:55].strip()
        self.prop["TI"] = record[0][64:74].strip()
        self.prop["DTI"] = record[0][74:76].strip()
        self.prop["C"] = record[0][76].strip()
        self.prop["UN"] = record[0][77:79].strip()
        self.prop["Q"] = record[0][79].strip()
        self.load_prop(record[1:])


class AlphaRecord(DecayRecord):
    def __init__(self, dataset, record, comments, xref, dest_level):
        super().__init__(dataset, record, comments, xref, dest_level)
        self.prop["E"] = record[0][9:19].strip()
        self.prop["DE"] = record[0][19:21].strip()
        self.prop["IA"] = record[0][21:29].strip()
        self.prop["DIA"] = record[0][29:31].strip()
        self.prop["HF"] = record[0][31:39].strip()
        self.prop["DHF"] = record[0][39:41].strip()
        self.prop["C"] = record[0][76].strip()
        self.prop["Q"] = record[0][79].strip()
        self.load_prop(record[1:])


class ParticleRecord(DecayRecord):
    def __init__(self, dataset, record, comments, xref, dest_level):
        super().__init__(dataset, record, comments, xref, dest_level)
        self.prop["D"] = record[0][7]
        self.prop["Particle"] = record[0][8]
        self.prop["E"] = record[0][9:19].strip()
        self.prop["DE"] = record[0][19:21].strip()
        self.prop["IP"] = record[0][21:29].strip()
        self.prop["DIP"] = record[0][29:31].strip()
        self.prop["EI"] = record[0][31:39].strip()
        self.prop["T"] = record[0][39:49].strip()
        self.prop["DT"] = record[0][49:55].strip()
        self.prop["L"] = record[0][55:64].strip()
        self.prop["C"] = record[0][76].strip()
        self.prop["COIN"] = record[0][78].strip()
        self.prop["Q"] = record[0][79].strip()
        self.load_prop(record[1:])

        self.prompt_emission = self.prop["D"] == ' '
        self.delayed_emission = self.prop["D"] == 'D'


class GammaRecord(DecayRecord):
    def __init__(self, dataset, record, comments, xref, orig_level):
        super().__init__(dataset, record, comments, xref, dest_level=None)
        self.orig_level = orig_level
        if self.orig_level:
            self.orig_level.add_decay(self)
        self.prop["E"] = record[0][9:19].strip()
        self.prop["DE"] = record[0][19:21].strip()
        self.prop["RI"] = record[0][21:29].strip()
        self.prop["DRI"] = record[0][29:31].strip()
        self.prop["M"] = record[0][31:41].strip()
        self.prop["MR"] = record[0][41:49].strip()
        self.prop["DMR"] = record[0][49:55].strip()
        self.prop["CC"] = record[0][55:62].strip()
        self.prop["DCC"] = record[0][62:64].strip()
        self.prop["TI"] = record[0][64:74].strip()
        self.prop["DTI"] = record[0][74:76].strip()
        self.prop["C"] = record[0][76].strip()
        self.prop["COIN"] = record[0][78].strip()
        self.prop["Q"] = record[0][79].strip()
        self.load_prop(record[1:])

        self.energy = Quantity(self.prop["E"], self.prop["DE"])
        self.rel_intensity = Quantity(self.prop["RI"], self.prop["DRI"])
        self.multipolarity = self.prop["M"]
        self.mixing_ratio = Quantity(self.prop["MR"], self.prop["DMR"])
        self.conversion_coeff = Quantity(self.prop["CC"], self.prop["DCC"])
        self.rel_tot_trans_intensity = Quantity(self.prop["TI"], self.prop["DTI"])
        self.questionable = (self.prop["Q"] == "?")
        self.expected = (self.prop["Q"] == "S")

        self.attr = dict()
        for k, v in self.prop.items():
            if k[0:2] == "BE" or k[0:2] == "BM":
                self.attr[k] = Quantity(v, has_unit=False)

        self._determine_dest_level()
    
    def _determine_dest_level(self):
        if "FL" in self.prop:
            if self.prop["FL"] == "?":
                return
            dest_energy = Quantity(self.prop["FL"]).val
        elif self.orig_level:
            energy_gamma = self.energy.val
            mass, _ = az_from_nucid(self.dataset.nucid)
            amu = physical_constants[
                "atomic mass constant energy equivalent in MeV"][0]
            energy_i = (energy_gamma * (1 + 2* (.001 * energy_gamma) / (mass * amu)))
            dest_energy = self.orig_level.energy.val - energy_i
        else:
            return
        try:
            self.dest_level = min(
                [l for l in self.dataset.levels if l.energy.offset == self.energy.offset],
                key=lambda x: abs(x.energy.val - dest_energy))
            self.dest_level.populating.append(self)
        except ValueError:
            pass


class ReferenceRecord(BaseRecord):
    def __init__(self, dataset, line):
        self.prop = dict()
        self.dataset = dataset
        self.prop["MASS"] = line[0:3].strip()
        self.prop["KEYNUM"] = line[9:17].strip()
        self.prop["REFERENCE"] = line[17:80].strip()


def get_record_type(record):
    if record[0][7] == "X":
        return CrossReferenceRecord
    if record[0][7] == "Q":
        return QValueRecord
    if record[0][7] == "L":
        return LevelRecord
    if record[0][7] == "B":
        return BetaRecord
    if record[0][7] == "E":
        return ECRecord
    if record[0][7] == "A":
        return AlphaRecord
    if record[0][7] == "G":
        return GammaRecord
    if record[0][7] in " D" and record[0][8] in "PAN":
        return ParticleRecord
    else:
        raise NotImplementedError(f"Unknown record with type '{record[0][7]}': '{record[0]}'")


class Nucleus:
    def __init__(self, ensdf: ENSDF, mass: int, protons: int):
        self.ensdf = ensdf
        self.adopted_levels = ensdf.get_adopted_levels((mass, protons))
    
    def get_isomers(self):
        if self.adopted_levels.levels[0]:
            yield self.adopted_levels.levels[0]
        if self.adopted_levels.levels[1:]:
            for level in self.adopted_levels.levels[1:]:
                if level.metastable:
                    yield level

