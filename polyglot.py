#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import csv
import glob
import codecs
import difflib
import argparse
import xml.etree.ElementTree as etree
import xml.dom.minidom as mdom

"""
    Naming conventions:
        1. <language code>-<country code>-<brand-name>.csv
        2. We will follow ISO639-2 http://www.loc.gov/standards/iso639-2/php/code_list.php
            for language names and ISO 3166-1-alpha-2
            http://www.iso.org/iso/en/prods-services/iso3166ma/02iso-3166-code-lists/list-en1.html
            for country codes.
        3. Only language code is mandatory. Other is optional

    We will distinguish master "en.csv" file and other translations files.
        1. "en.csv" will contain rows: "key | en strings | en string or nothing | platform"
        2. Other files will contain "key | en string | translation | optional comment"
        3. We will ignore last column on all languages except main "en" file
"""


class Polyglot:
    """ This class contains global constants and global settings that
        was received from command line
    """

    class Platform:
        Android = "android"
        Apple = "ios"
        Windows = "wp"
        Blackberry57 = "bb"
        Qt = "qt"
        Any = "any"

    class Action:
        Generate = "generate"
        Deduplicate = "simplify"
        Analyze = "analyze"

    # Consts
    AliasIndex = 0
    EnglishInxed = 1
    TranslationIndex = 2
    PlathformIndex = 3
    CommentIndex = 4

    SourceFileExt = '.csv'
    MasterFileName = 'en' + SourceFileExt

    SupportedPlatforms = [Platform.Android, Platform.Apple, Platform.Windows, Platform.Blackberry57]
    Actions = [Action.Generate, Action.Analyze]

    BlackberryPackage = 'com.PGLtd.strings'
    BaseNames = {
        Platform.Android: "strings", 
        Platform.Apple: "Localizable", 
        Platform.Windows: "LocalizedStrings", 
        Platform.Blackberry57: "LocalizedStrings"
    }

    # Vars
    CsvRootPath = None
    CsvEnPath = None
    CsvXXPath = []

    MasterDirName = None

    OutputRoot = './'

    @staticmethod
    def csv_reader_from_file(csv_file):
        """ this method handle links on windows also
        """
        try:
            dialect = csv.Sniffer().sniff(csv_file.read(1024), delimiters=";,")
            csv_file.seek(0)
            return csv.reader(csv_file, dialect)
        except (csv.Error, UnicodeDecodeError) as e:
            # process symbolic links on windows (exception may be because symlink)
            if os.name == 'nt':
                with open(csv_file.name, 'rb') as link_file:
                    data = link_file.readline()
                    target_bytes = []
                    link_type = ""
                    
                    if data.startswith(b'!<symlink>\xFF\xFE'):
                        link_type = "Cygwin"
                        target_bytes = data.replace(b'!<symlink>\xFF\xFE', b'').replace(b'\x00', b'')
                    else:
                        link_type = "Unix"
                        target_bytes = data
                    
                    target = os.path.dirname(link_file.name) + os.sep + target_bytes.decode('UTF-8')
                    
                    print ("%s symbolic link %s -> %s" % (link_type, link_file.name, target))
                    
                    real_csv_file = open(target, encoding='UTF-8')
                    return Polyglot.csv_reader_from_file(real_csv_file)
    
    @staticmethod
    def init(cmd_args):
        csv_path = cmd_args.path
        Polyglot.MasterDirName = cmd_args.master_dir

        if not (os.path.exists(csv_path)):
            raise ValueError("Path '" + csv_path + "' noes not exists. Please specify correct")

        if os.path.isdir(csv_path):  # batch-mode
            Polyglot.CsvRootPath = csv_path[:-1] if csv_path.endswith('/') else csv_path

            if os.path.exists(os.path.join(Polyglot.CsvRootPath, Polyglot.MasterFileName)):

                Polyglot.CsvEnPath = os.path.join(Polyglot.CsvRootPath, Polyglot.MasterFileName)

                for csv_basename in glob.glob(Polyglot.CsvRootPath + '/*' + Polyglot.SourceFileExt):
                    # print(os.path.abspath(csv_basename))
                    Polyglot.CsvXXPath.append(os.path.abspath(csv_basename))

            else:
                raise ValueError("Unable to find '{0}'. Exit.".format(csv_path + '/' + Polyglot.MasterFileName))

        else:  # single file
            Polyglot.CsvRootPath = os.path.dirname(csv_path)
            Polyglot.CsvXXPath.append(os.path.abspath(csv_path))

            if os.path.exists(os.path.join(Polyglot.CsvRootPath, Polyglot.MasterFileName)):
                # print(os.path.abspath(Polyglot.CsvEnPath))
                Polyglot.CsvEnPath = os.path.join(Polyglot.CsvRootPath, Polyglot.MasterFileName)

            else:
                raise ValueError("Unable to find '{0}'. Exit.".format(csv_path + '/' + Polyglot.MasterFileName))

        Polyglot.OutputRoot = args.output_dir
        Polyglot.FileBaseName = 'strings'
        Polyglot.BlackberryPackage = args.blackberry_package


class AbstractBuilder:
    def __init__(self):
        self.template_fixing_enabled = True

    def add_string(self, key, value, comment):
        raise NotImplementedError("method 'add_string' not implemented in subclass")

    def get_result(self, output, lc, cc):
        raise NotImplementedError("method 'get_result' not implemented in subclass")

    def fix_template_placeholder(self, value):
        raise NotImplementedError("method 'fix_template' not implemented in subclass")

    @staticmethod
    def prettify(xml):
        xml_byte = etree.tostring(xml, encoding='UTF-8', method='xml')
        xml_str = xml_byte.decode(encoding='UTF-8')

        xml_again = mdom.parseString(xml_str)
        pretty_xml_str = xml_again.toprettyxml(indent='\t', encoding='UTF-8').decode(encoding='UTF-8')

        return pretty_xml_str

    def fix_template(self, value):
        if self.template_fixing_enabled:
            index = 0
            for param in re.findall(r"\{[A-Za-z0-9_ ]+\}", value):
                value = value.replace(param, self.fix_template_placeholder(param, index))
                index += 1

        return value


class AndroidBuilder(AbstractBuilder):
    """ http://developer.android.com/guide/topics/resources/string-resource.html
    """

    def __init__(self):
        self.output_xml = etree.Element("resources")
        self.platform = Polyglot.Platform.Android
        self.template_fixing_enabled = False
        self.target_file = "{output}/android/res/values-{lc}{cc}/{basename}.xml"

    def add_string(self, key, value, comment):
        if comment:
            comment_node = etree.Comment(comment)
            self.output_xml.append(comment_node)

        value = self.fix_template(value)

        string_node = etree.SubElement(self.output_xml, "string")
        string_node.set("name", key)

        # escape symbols
        string_node.text = value.replace('\'', '\\\'')

    def fix_template_placeholder(self, value, index):
        """ http://developer.android.com/reference/android/content/res/Resources.html#getQuantityString(int, int, java.lang.Object...)
        """
        return "{{0}}".format(str(index))

    def get_result(self, output, lc, cc):
        # fix for case when cc missing
        cc = '-r' + cc if cc else ''

        return {self.target_file.format(output=output,  basename=Polyglot.BaseNames[self.platform], lc=lc, cc=cc): AbstractBuilder.prettify(
            self.output_xml)}


class IOSBuilder(AbstractBuilder):
    """ https://developer.apple.com/library/mac/documentation/Cocoa/Conceptual/LoadingResources/Strings/Strings.html
    """

    def __init__(self):
        self.output_plain = ''
        self.platform = Polyglot.Platform.Apple
        self.template_fixing_enabled = False
        self.target_file = "{output}/ios/{lc}{cc}.lproj/{basename}.strings"

    def add_string(self, key, value, comment):
        entry = ''
        if comment:
            entry += "/* {0} */\n".format(comment)

        value = self.fix_template(value)

        # escape symbols
        value = value.replace('\"', '\\\"')
        value = value.replace('\\u0020', ' ')   # fast solution, need to find long term solution

        entry += "\"{alias}\" = \"{value}\";\n".format(alias=key, value=value)

        self.output_plain += entry

    def fix_template_placeholder(self, value, index):
        """ https://developer.apple.com/library/mac/documentation/Cocoa/Conceptual/Strings/Articles/FormatStrings.html
        """
        return '%@'

    def get_result(self, output, lc, cc):
        # fix for case when cc missing
        cc = '-' + cc if cc else ''

        return {self.target_file.format(output=output, basename=Polyglot.BaseNames[self.platform], lc=lc, cc=cc): self.output_plain}


class ResXBuilder(AbstractBuilder):
    """ http://msdn.microsoft.com/en-us/library/ekyft91f.aspx
    """

    def __init__(self):
        self.output_xml = etree.Element('root')
        self.platform = Polyglot.Platform.Windows

        self.template_fixing_enabled = True
        self.target_file = "{output}/wp/{basename}.{lc}{cc}.resx"

        # build header
        # internal XML schema missing
        resheader_node = etree.SubElement(self.output_xml, 'resheader')
        resheader_node.set('name', 'resmimetype')
        resheader_node = etree.SubElement(resheader_node, 'value')
        resheader_node.text = 'text/microsoft-resx'

        resheader_node = etree.SubElement(self.output_xml, 'resheader')
        resheader_node.set('name', 'version')
        resheader_node = etree.SubElement(resheader_node, 'value')
        resheader_node.text = '2.0'

        resheader_node = etree.SubElement(self.output_xml, 'resheader')
        resheader_node.set('name', 'reader')
        resheader_node = etree.SubElement(resheader_node, 'value')
        resheader_node.text = 'System.Resources.ResXResourceReader, System.Windows.Forms, Version=4.0.0.0, ' \
                              'Culture=neutral, PublicKeyToken=b77a5c561934e089'

        resheader_node = etree.SubElement(self.output_xml, 'resheader')
        resheader_node.set('name', 'writer')
        resheader_node = etree.SubElement(resheader_node, 'value')
        resheader_node.text = 'System.Resources.ResXResourceWriter, System.Windows.Forms, Version=4.0.0.0, ' \
                              'Culture=neutral, PublicKeyToken=b77a5c561934e089'

    def add_string(self, key, value, comment):
        key_node = etree.SubElement(self.output_xml, 'data')

        key_node.set('name', key)
        key_node.set('xml:space', 'preserve')

        value = self.fix_template(value)
        value = value.replace('\\u0020', ' ')   # fast solution, need to find long term solution

        value_node = etree.SubElement(key_node, 'value')
        value_node.text = value

        if comment:
            comment_node = etree.SubElement(key_node, 'comment')
            comment_node.text = comment

    def fix_template_placeholder(self, value, index):
        """ http://msdn.microsoft.com/en-us/library/system.string.format.aspx
        """
        return '{{0}}'.format(str(index))

    def get_result(self, output, lc, cc):
        # fix for case when cc missing
        cc = '-' + cc if cc else ''

        return {self.target_file.format(output=output, basename=Polyglot.BaseNames[self.platform], lc=lc, cc=cc): AbstractBuilder.prettify(
            self.output_xml)}


class BlackBerry57Builder(AbstractBuilder):
    """ https://developer.blackberry.com/bbos/java/documentation/localize_apps_2006594_11.html
    """

    def __init__(self):
        self.header = 'package {pkg};\n\n'.format(pkg=Polyglot.BlackberryPackage)
        self.impl = ''
        self.header_idx = 0
        self.platform = Polyglot.Platform.Blackberry57
        self.template_fixing_enabled = True
        self.target_header_file = "{output}/bb/res/{bb_package_path}/{basename}.rrh"
        self.target_source_file = "{output}/bb/res/{bb_package_path}/{basename}_{lc}{cc}.rrc"

    def add_string(self, key, value, comment):
        header_entry_template = '{alias}#0={index};\n'
        impl_entry_template = '{alias}#0="{value}";\n'

        value = self.fix_template(value)
        # escape symbols
        value = value.replace('\"', '\\\"')

        self.header += header_entry_template.format(alias=key, index=self.header_idx)
        self.impl += impl_entry_template.format(alias=key, value=value)
        self.header_idx += 1

    def fix_template_placeholder(self, value, index):
        """ http://www.blackberry.com/developers/docs/4.5.0api/javax/microedition/global/Formatter.html
        """
        return "{{0}}".format(str(index))

    def get_result(self, output, lc, cc):
        if self.impl:
            # fix for case when cc missing
            cc = '_' + cc if cc else ''

            bb_package_path = Polyglot.BlackberryPackage.replace('.', '/')

            header_path = self.target_header_file.format(output=output,
                                                         bb_package_path=bb_package_path,
                                                         basename=Polyglot.BaseNames[self.platform])

            source_path = self.target_source_file.format(output=output,
                                                         bb_package_path=bb_package_path,
                                                         basename=Polyglot.BaseNames[self.platform],
                                                         lc=lc,
                                                         cc=cc)

            return {header_path: self.header, source_path: self.impl}
        else:
            return {}


class QtBuilder(AbstractBuilder):
    """ http://qt-project.org/doc/qt-4.8/linguist-ts-file-format.html
    """

    def __init__(self):
        self.output_xml = etree.Element('TS')
        self.output_xml.set('version', '2.1')
        self.platform = Polyglot.Platform.Qt

        self.context = etree.SubElement(self.output_xml, 'context')
        name = etree.SubElement(self.context, 'name')
        name.text = '!AUTO GENERATED, FIXME IF YOU CAN!'

        self.template_fixing_enabled = False
        self.target_source_file = "{output}/qt/{basename}_{lc}{cc}.tc"

    def add_string(self, key, value, comment):
        message = etree.SubElement(self.context, 'message')

        source_node = etree.SubElement(message, 'source')
        source_node.text = key

        if comment:
            comment_node = etree.SubElement(message, 'comment')
            comment_node.text = comment

        value = self.fix_template(value)

        translation_node = etree.SubElement(message, 'translation')
        translation_node.text = value

    def get_result(self, output, lc, cc):
        # fix for case when cc missing
        cc = "_" + cc if cc else ""

        self.output_xml.set('language', lc + cc)

        return {self.target_file.format(output=output, basename=Polyglot.BaseNames[self.platform], lc=lc, cc=cc): AbstractBuilder.prettify(
            self.output_xml)}


class Worker:
    """ Generator for single file
    """

    def __init__(self, platforms, lc, cc):
        self.builders = []
        self.lc = lc
        self.cc = cc

        for p in platforms:
            if p == Polyglot.Platform.Android:
                self.builders.append(AndroidBuilder())
            elif p == Polyglot.Platform.Apple:
                self.builders.append(IOSBuilder())
            elif p == Polyglot.Platform.Windows:
                self.builders.append(ResXBuilder())
            elif p == Polyglot.Platform.Blackberry57:
                self.builders.append(BlackBerry57Builder())
            elif p == Polyglot.Platform.Qt:
                self.builders.append(QtBuilder())
            else:
                print("Unsupported platform '" + p + "'. Please try one of " + str(Polyglot.SupportedPlatforms))

    def process_row(self, row, enable_comments, pk_map):
        try:
            key = row[Polyglot.AliasIndex]
            value = row[Polyglot.TranslationIndex]
            platforms = pk_map[key] if key in pk_map else ' '.join(Polyglot.SupportedPlatforms)

            comment = row[Polyglot.CommentIndex] if enable_comments and len(row) > 4 else None

            for b in self.builders:
                if b.platform in platforms:
                    # FIX unprocessed double quote escaping 
                    # http://stackoverflow.com/questions/7334752/problem-due-to-double-quote-while-parsing-csv
                    while '""' in value:
                        value = value.replace('""', '"')
                    b.add_string(key, value, comment)
        except IndexError:
            print("Error row=" + str(row))

    def process(self, csv_path, enable_comments, pk_map):
        """ @arg csv_path
            @arg enable_comments
            @arg pk_map - platform/key map
        """

        existing_keys = []
        with open(csv_path, encoding='UTF-8') as csv_file:
            reader = Polyglot.csv_reader_from_file(csv_file)

            for row in reader:
                existing_keys.append(row[0])
                self.process_row(row, enable_comments, pk_map)

        if Polyglot.MasterDirName:
            master_csv_path = os.path.join(Polyglot.MasterDirName, os.path.basename(csv_path))

            with open(master_csv_path, encoding='UTF-8') as csv_file:
                reader = Polyglot.csv_reader_from_file(csv_file)

                for row in reader:
                    if row[0] not in existing_keys:
                        self.process_row(row, enable_comments, pk_map)

        for b in self.builders:
            output_files = b.get_result(Polyglot.OutputRoot, self.lc, self.cc)

            for file_name in output_files.keys():

                new_filename = file_name
                idx = 1
                while os.path.exists(new_filename):
                    file_name_comps = os.path.splitext(file_name)
                    new_filename = file_name_comps[0] + ' ' + str(idx) + file_name_comps[1]
                    idx += 1

                dir_name = os.path.dirname(os.path.abspath(new_filename))
                if not os.path.exists(dir_name):
                    os.makedirs(dir_name, exist_ok=True)

                file = codecs.open(new_filename, mode='w', encoding='UTF-8')
                file.write(output_files[file_name])
                file.close()

                print("Generated '{0}'".format(new_filename))


class Director:
    """ Manage worker objects
    """

    def __init__(self, platforms, enable_comments):
        if Polyglot.Platform.Any in platforms:
            del platforms[:]
            platforms.extend(Polyglot.SupportedPlatforms)

        self.uplatforms = set(platforms)
        self.comments = enable_comments

    def process(self):
        pk_map = Director.build_platforms_map(Polyglot.CsvEnPath)

        # TODO multi threading
        for csv_path in Polyglot.CsvXXPath:
            print("Start processing resources '{0}'".format(csv_path))

            lc, cc = Director.find_lc_and_cc(csv_path)

            w = Worker(self.uplatforms, lc, cc)
            w.process(csv_path, self.comments, pk_map)

        # Note for BB 5.0
        if Polyglot.Platform.Blackberry57 in self.uplatforms:
            print("\nNOTE: If your Blackberry target os is 5.0 or lower:\n"
                  "      1. make sure that for each string_xx_YY.rrc you have it copy with name string_xx.rrc.\n"
                  "      2. make sure that for each string_xx_YY.rrh you have it copy with name string_xx.rrh.")

    @staticmethod
    def build_platforms_map(csv_path):
        """ only english csv contains information about platforms for particular string
            this method prepare map with this kind of information
        """
        result = {}

        with open(csv_path, encoding='UTF-8') as csv_file:
            reader = Polyglot.csv_reader_from_file(csv_file)

            for row in reader:
                key = row[Polyglot.AliasIndex]
                platforms = row[Polyglot.PlathformIndex]

                result[key] = platforms


        if Polyglot.MasterDirName:
            master_csv_path = os.path.join(Polyglot.MasterDirName, os.path.basename(csv_path))

            with open(master_csv_path, encoding='UTF-8') as csv_file:
                reader = Polyglot.csv_reader_from_file(csv_file)

                for row in reader:
                    key = row[Polyglot.AliasIndex]
                    platforms = row[Polyglot.PlathformIndex]

                    result[key] = platforms

        return result

    @staticmethod
    def find_lc_and_cc(csv_path):
        csv_filename = os.path.splitext(os.path.basename(csv_path))[0]

        lccc = [i for i in csv_filename.split('-') if len(i) == 2]

        return lccc[0], lccc[1] if len(lccc) > 1 else None

class Analyzer:
    def process(self):
        print("Start analyzing resources '{0}'".format(Polyglot.CsvRootPath))

        alias, book, adup = self.alias_duplicates_detector(Polyglot.CsvEnPath)
        exact, fuzzy = self.string_duplicates_detector(alias, book)

        print(
            " Exact duplicates [{0}]: \n\t{1}\n\n Fuzzy duplicates [{2}]: \n\t{3}\n\n Alias duplicates [{4}]: \n\t{5}\n"
            .format(len(exact),
                    '\n\t'.join(["'{0}' keys={1}".format(key, str(set(value))) for (key, value) in exact.items()]),
                    len(fuzzy),
                    '\n\t'.join(["'{0}' ~ {1}".format(key, str(set(value))) for (key, value) in fuzzy.items()]),
                    len(adup), '\n\t'.join(adup) if len(adup) > 0 else 'Good!'))

        if len(Polyglot.CsvXXPath) > 1:  # integrity possible only for batch-mode
            integrity = self.integrity_check(set(alias))

            print(" Integrity report [{0}]: ".format(len(integrity.keys())))
            for xx in integrity.keys():
                missing = integrity[xx][0]
                redundant = integrity[xx][1]

                print("\tFile '{0}' ".format(xx))
                if len(missing) == 0 and len(redundant) == 0:
                    print("\t\tGood!")
                else:
                    if len(missing) > 0:
                        print("\t\tMissing   : " + str(missing))
                    if len(redundant) > 0:
                        print("\t\tRedundant : " + str(redundant))


    def alias_duplicates_detector(self, csv_path):
        book = []
        aliases = []
        alias_duplicates = []

        with open(csv_path, encoding='UTF-8') as csv_file:
            reader = Polyglot.csv_reader_from_file(csv_file)

            for row in reader:
                if row[Polyglot.AliasIndex] in aliases:
                    alias_duplicates.append(row[Polyglot.AliasIndex])
                aliases.append(row[Polyglot.AliasIndex])
                book.append(row[Polyglot.TranslationIndex])

        return aliases, book, alias_duplicates

    def string_duplicates_detector(self, alias, book):
        exact_duplicates = {}
        fuzzy_duplicates = {}

        index = 0
        for word in book:
            candidates = list(book)
            candidates.remove(word)

            results = difflib.get_close_matches(word, candidates, 5, 0.86)  # a little bit magic

            if len(results) > 0:
                if word in results:  # exact duplicate
                    if word in exact_duplicates.keys():
                        exact_duplicates[word].append(alias[index])
                    else:
                        exact_duplicates[word] = [alias[index]]
                else:  # fuzzy duplicate
                    for result in results:
                        if result in fuzzy_duplicates.keys() and word in fuzzy_duplicates[result]:
                            # need to avoid loop A -> B && B -> A
                            pass
                        elif word not in fuzzy_duplicates.keys():
                            fuzzy_duplicates[word] = [result]
                        elif word in fuzzy_duplicates.keys() and len(fuzzy_duplicates[word]) == 0:
                            fuzzy_duplicates[word] = [result]
                        else:
                            fuzzy_duplicates[word].append(result)

            index += 1

        return exact_duplicates, fuzzy_duplicates

    def integrity_check(self, alias):
        # { filename : [[missing_keys], [redundant_keys]] }
        report = {}

        for csv_path in Polyglot.CsvXXPath:
            xx_alias = []
            with open(csv_path, encoding='UTF-8') as csv_file:
                reader = Polyglot.csv_reader_from_file(csv_file)

                for row in reader:
                    xx_alias.append(row[Polyglot.AliasIndex])

            xx_missing = []

            for a in alias:
                if a in xx_alias:
                    xx_alias.remove(a)
                else:
                    xx_missing.append(a)

            xx_redundant = xx_alias

            report[csv_path] = [xx_missing, xx_redundant]

        return report


class Simplifier:
    def process(self, csv_path):
        with open(csv_path, encoding='UTF-8') as csv_file:
            dialect = csv.Sniffer().sniff(csv_file.read(1024), delimiters=";,")
            csv_file.seek(0)

            reader = csv.reader(csv_file, dialect)
            rows_dict = {}
            for row in reader:
                word = row[Polyglot.EnglishInxed]

                if word in rows_dict.keys():
                    first = rows_dict[word]

                    aliases = self.select_alias(first[0], row[0])
                    platforms = self.merge_platforms(first[2], row[2])

                    first[0] = aliases[0]
                    first[2] = platforms
                    if len(first) < 4:
                        first.append('')
                    first[3] = first[3] + '/' + aliases[1]

                    pass

                else:
                    rows_dict[word] = row
                    pass

        csv_result_path = '{0}.temp'.format(csv_path)
        with open(csv_result_path, mode='x', encoding='UTF-8') as csv_result_file:
            writer = csv.writer(csv_result_file, dialect)
            writer.writerows(rows_dict.values())

    def merge_platforms(self, pl1, pl2, separator=' '):
        """ Just merge two space separated list
        :param pl1: first string
        :param pl2: second string
        :return:
        """

        p1 = pl1.split(separator)
        p2 = pl2.split(separator)

        p3 = set(p1 + p2)

        return ' '.join(p3)

    def select_alias(self, a1, a2):
        """ This method sorts aliases by priority. android aliases will win by condition
        written below
        :param a1: first alias
        :param a2: second alias
        :return: aliases due to it's priority
        """

        a1_w = 0
        a2_w = 0

        # if you have space inside its bad
        if ' ' in a1:
            a1_w -= 2

        if ' ' in a2:
            a2_w -= 2

        # if you have upper letter inside it less worse
        for c in a1:
            if c.isupper():
                a1_w -= 1

        for c in a2:
            if c.isupper():
                a2_w -= 1

        return [a1, a2] if a1_w > a2_w else [a2, a1]


if __name__ == "__main__":

    parser = argparse.ArgumentParser(prog='polyglot.py', add_help=True,
                                     formatter_class=argparse.RawDescriptionHelpFormatter,
                                     description='Tool that help generate static strings file for different platforms ' + str(Polyglot.SupportedPlatforms),
                                     epilog='\nExamples of Use:\n' \
                                            '\t./polyglot.py -p examples/en.csv            - specify single file for generation single file\n' \
                                            '\t./polyglot.py -p examples                   - specify directory for batch processing, many files will be generated\n' \
                                            '\t./polyglot.py -p examples/fr.csv -m pg - in generated files strings form pg/fr.csv dir will be overwriten by stanley/fr.csv \n' \
                                            '\t./polyglot.py -a analyze -p examples/fr.csv - check for duplicates in strings and in aliases (first column)\n' \
                                    )

    group = parser.add_argument_group('General arguments', 'arguments that applies to all platform independently')

    group.add_argument ('-a',
                        '--action',
                        required=False,
                        default=Polyglot.Action.Generate,
                        help='Supported actions {0}'.format(Polyglot.Actions))

    group.add_argument ('-p',
                        '--path',
                        required=True,
                        help='Path to csv file (or directory with csv files) that have specific format.'
                             'column1=key, column2=string, column3=translation '
                             'column3=coma-separated list with platforms column4=comment')

    group.add_argument ('-pl',
                        '--platform',
                        nargs='+',
                        default=[Polyglot.Platform.Any],
                        required=False,
                        help='List of platforms {0}. By default any'.format(Polyglot.SupportedPlatforms))

    group.add_argument ('-m',
                        '--master-dir',
                        default=None,
                        required=False,
                        help='Enable "master" mode. Directory where the strings will be taken to override. It may be overwriten by strings from -p/--path')

    group.add_argument ('-o',
                        '--output-dir',
                        default='output',
                        required=False,
                        help='Directory where result will be placed'.format(Polyglot.SupportedPlatforms))

    group.add_argument ('-ec',
                        '--enable-comments',
                        action='store_true',
                        required=False,
                        help='This flag help to generate comments column4=comment in csv. Disabled by default')

    group = parser.add_argument_group('Platform-specific arguments', 'arguments that applies to specified platform')

    group.add_argument ('-bbpkg',
                        '--blackberry-package',
                        default='com.PGLtd.strings',
                        required=False,
                        help='package name for blackberry rrh file. for more details see blackberry docs')

    args = parser.parse_args()

    try:
        Polyglot.init(args)

        if args.action == Polyglot.Action.Generate:
            g = Director(args.platform, args.enable_comments)
            g.process()

        elif args.action == Polyglot.Action.Analyze:

            a = Analyzer()
            a.process()

        elif args.action == Polyglot.Action.Deduplicate:

            s = Simplifier()
            s.process(args.path)

            pass
        else:
            parser.print_help()

    except Exception as e:
        print("Unexpected error '" + str(e) + "'")
        raise e
