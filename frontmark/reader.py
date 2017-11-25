import collections
import logging
import re

try:
    import yaml
except ImportError as e:  # pragma: no cover
    yaml = False

from pelican.readers import BaseReader
from pelican.utils import pelican_open


try:
    from markdown import Markdown
except ImportError:
    Markdown = False # NOQA

from .signals import frontmark_yaml_register

log = logging.getLogger(__name__)


DELIMITER = '---'
BOUNDARY = re.compile(r'^{0}$'.format(DELIMITER), re.MULTILINE)
STR_TAG = 'tag:yaml.org,2002:str'

INTERNAL_LINK = re.compile(r'^%7B(\w+)%7D')


class FrontmarkReader(BaseReader):
    """
    Reader for Markdown files with YAML metadata
    """

    enabled = bool(Markdown) and bool(yaml)
    file_extensions = ['md']

    def __init__(self, *args, **kwargs):
        super(FrontmarkReader, self).__init__(*args, **kwargs)
        settings = self.settings['MARKDOWN']
        settings.setdefault('extension_configs', {})
        settings.setdefault('extensions', [])
        for extension in settings['extension_configs'].keys():
            if extension not in settings['extensions']:
                settings['extensions'].append(extension)
        if 'markdown.extensions.meta' not in settings['extensions']:
            settings['extensions'].append('markdown.extensions.meta')

        self._source_path = None
        self._md = None

    def read(self, source_path):
        self._source_path = source_path
        self._md = Markdown(**self.settings['MARKDOWN'])

        with pelican_open(source_path) as text:
            metadata, content = self._parse(text)

        content = self._render(content)
        return content.strip(), self._parse_metadata(metadata)

    def _parse(self, text):
        """
        Parse text with frontmatter, return metadata and content.
        If frontmatter is not found, returns an empty metadata dictionary and original text content.
        """
        # ensure unicode first
        text = str(text).strip()

        if not text.startswith(DELIMITER):
            return {}, text

        try:
            _, fm, content = BOUNDARY.split(text, 2)
        except ValueError:
            # if we can't split, bail
            return {}, text
        # loader_class = self.loader_factory(self)
        metadata = yaml.load(fm, Loader=self.loader_class)
        metadata = metadata if (isinstance(metadata, dict)) else {}
        return metadata, content

    def _parse_metadata(self, meta):
        """Return the dict containing document metadata"""
        formatted_fields = self.settings['FORMATTED_FIELDS']

        output = collections.OrderedDict()
        for name, value in meta.items():
            name = name.lower()
            if name in formatted_fields:
                rendered = self._render(value).strip()
                output[name] = self.process_metadata(name, rendered)
            else:
                output[name] = self.process_metadata(name, value)
        return output

    def _render(self, text):
        """Render Markdown with settings taken in account"""
        return self._md.convert(text)

    def yaml_markdown_constructor(self, loader, node):
        """Allows to optionnaly parse Markdown in multiline literals"""
        value = loader.construct_scalar(node)
        return self._render(value).strip()

    def yaml_multiline_as_markdown_constructor(self, loader, node):
        """Allows to optionally parse Markdown in multiline literals"""
        value = loader.construct_scalar(node)
        return self._render(value).strip() if node.style == '|' else value

    @property
    def loader_class(self):
        class FrontmarkLoader(yaml.Loader):
            """
            Custom YAML Loader for frontmark

            - Mapping order is respected (wiht OrderedDict)
            """
            def construct_mapping(self, node, deep=False):
                """User OrderedDict as default for mappings"""
                return collections.OrderedDict(self.construct_pairs(node))

        FrontmarkLoader.add_constructor('!md', self.yaml_markdown_constructor)
        if self.settings.get('FRONTMARK_PARSE_LITERAL', True):
            FrontmarkLoader.add_constructor(STR_TAG, self.yaml_multiline_as_markdown_constructor)
        for _, pair in frontmark_yaml_register.send(self):
            if not len(pair) == 2:
                log.warning('Ignoring YAML type (%s), expected a (tag, handler) tuple', pair)
                continue
            tag, constructor = pair
            FrontmarkLoader.add_constructor(tag, constructor)

        return FrontmarkLoader


def add_reader(readers):  # pragma: no cover
    for k in FrontmarkReader.file_extensions:
        readers.reader_classes[k] = FrontmarkReader
