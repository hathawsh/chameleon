import os
import shutil
import tempfile

from unittest import TestCase
from functools import wraps

try:
    str = unicode
except:
    pass


class TemplateFileTestCase(TestCase):
    @property
    def _class(self):
        from chameleon.template import BaseTemplateFile

        class TestTemplateFile(BaseTemplateFile):
            cook_count = 0

            def cook(self, body):
                self.cook_count += 1
                self._cooked = True

        return TestTemplateFile

    def _make_temporary_file(self):
        return tempfile.NamedTemporaryFile(suffix=".py")

    def test_cook_check(self):
        f = self._make_temporary_file()
        template = self._class(f.name)
        template.cook_check()
        self.assertEqual(template.cook_count, 1)

    def test_auto_reload(self):
        f = self._make_temporary_file()

        # set time in past
        os.utime(f.name, (0, 0))

        template = self._class(f.name, auto_reload=True)
        template.cook_check()

        # a second cook check makes no difference
        template.cook_check()
        self.assertEqual(template.cook_count, 1)

        # set current time on file
        os.utime(f.name, None)

        # file is reloaded
        template.cook_check()
        self.assertEqual(template.cook_count, 2)


class RenderTestCase(TestCase):
    root = os.path.dirname(__file__)

    def find_files(self, ext):
        from ..utils import read_encoded
        inputs = os.path.join(self.root, "inputs")
        outputs = os.path.join(self.root, "outputs")
        for filename in sorted(os.listdir(inputs)):
            name, extension = os.path.splitext(filename)
            if extension != ext:
                continue
            path = os.path.join(inputs, filename)
            f = open(path, 'rb')
            got = read_encoded(f.read())

            # if there's no output file, treat document as static and
            # expect intput equal to output
            import glob
            globbed = tuple(glob.iglob(os.path.join(
                outputs, "%s*%s" % (name.split('-', 1)[0], ext))))

            if not globbed:
                self.fail("Missing output for: %s." % name)

            for output in globbed:
                if not os.path.exists(output):
                    want = got
                else:
                    g = open(output, 'rb')
                    want = read_encoded(g.read())

                name, ext = os.path.splitext(output)
                basename = os.path.basename(name)
                if '-' in basename:
                    language = basename.split('-')[1]
                else:
                    language = None

                yield path, got, want, language


class ZopePageTemplatesTest(RenderTestCase):
    @property
    def factory(body):
        from ..zpt.template import PageTemplate
        return PageTemplate

    def template(body):
        def decorator(func):
            @wraps(func)
            def wrapper(self):
                template = self.factory(body)
                return func(self, template)

            return wrapper
        return decorator

    def error(body):
        def decorator(func):
            @wraps(func)
            def wrapper(self):
                from ..exc import TemplateError
                try:
                    self.factory(body)
                except TemplateError as exc:
                    return func(self, body, exc)
                else:
                    self.fail("Expected exception.")

            return wrapper
        return decorator

    @template("""<span tal:content='str(default)'>Default</span>""")
    def test_default_is_not_a_string(self, template):
        try:
            template()
        except RuntimeError as exc:
            self.assertTrue('symbolic value' in str(exc))
        else:
            self.fail("Expected error.")

    @error("""<tal:block replace='bad /// ' />""")
    def test_syntax_error(self, body, exc):
        self.assertTrue(body[exc.offset:].startswith('bad ///'))

    @error("""<tal:dummy attributes=\"dummy 'dummy'\" />""")
    def test_attributes_on_tal_tag_fails(self, body, exc):
        self.assertTrue(body[exc.offset:].startswith('dummy'))

    def test_custom_encoding_for_str_or_bytes(self):
        template = self.factory(
            b"<div>\xd2\xe5\xf1\xf2${text}</div>".decode('windows-1251'),
            encoding="windows-1251")

        text = b"\xd2\xe5\xf1\xf2"
        rendered = template(text=text)

        self.assertEqual(
            rendered.encode('windows-1251'),
            b"<div>\xd2\xe5\xf1\xf2\xd2\xe5\xf1\xf2</div>"
            )


class ZopeTemplatesTestSuite(RenderTestCase):
    def setUp(self):
        self.temp_path = temp_path = tempfile.mkdtemp()

        @self.addCleanup
        def cleanup(path=temp_path):
            shutil.rmtree(path)

    def test_files(self):
        from ..zpt.template import PageTemplate
        from ..zpt.template import PageTemplateFile
        from ..loader import TemplateLoader

        class Literal(object):
            def __init__(self, s):
                self.s = s

            def __html__(self):
                return self.s

            def __str__(self):
                raise RuntimeError(
                    "%r is a literal." % self.s)

        class Message(object):
            def __str__(self):
                return "message"

        import re

        def convert(msgid, **kwargs):
            if isinstance(msgid, Message):
                return translate(msgid, **kwargs)
            return str(msgid)

        def translate(msgid, domain=None, mapping=None, context=None,
                      target_language=None, default=None):
            if default is None:
                default = str(msgid)

            if isinstance(msgid, Message):
                default = "Message"

            if mapping:
                default = re.sub(r'\${([a-z_]+)}', r'%(\1)s', default) % \
                          mapping

            if target_language is None:
                return default

            if domain is None:
                with_domain = ""
            else:
                with_domain = " with domain '%s'" % domain

            stripped = default.rstrip('\n ')
            return "%s ('%s' translation into '%s'%s)%s" % (
                stripped, msgid, target_language, with_domain,
                default[len(stripped):]
                )

        loader = TemplateLoader(os.path.join(self.root, "inputs"))

        from chameleon.utils import DebuggingOutputStream

        for name, source, want, language in self.find_files(".pt"):
            if language is not None:
                name += '-' + language

            self.shortDescription = lambda: name
            template = PageTemplate(
                source,
                keep_source=True,
                output_stream_factory=DebuggingOutputStream,
                )

            import functools
            try:
                stream = template.render(
                    literal=Literal("<div>Hello world!</div>"),
                    message=Message(),
                    translate=functools.partial(
                        translate, target_language=language),
                    convert=functools.partial(
                        convert, target_language=language),
                    load=loader.bind(PageTemplateFile),
                    )
                tokens = tuple(stream)
                try:
                    got = "".join(tokens)
                except TypeError:
                    raise TypeError(repr(tokens))
            except:
                import traceback
                e = traceback.format_exc()
                self.fail("%s\n\n    Example source:\n\n%s" % (e, "\n".join(
                    ["%#03.d%s" % (lineno + 1, line and " " + line or "")
                     for (lineno, line) in
                     enumerate(template.source.split(
                         '\n'))])))

            from doctest import OutputChecker
            checker = OutputChecker()
            if checker.check_output(want, got, 0) is False:
                from doctest import Example
                example = Example(name, want)
                diff = checker.output_difference(
                    example, got, 0)
                self.fail("(%s) - \n%s\n\nCode:\n%s" % (
                    name, diff.rstrip('\n'), template.source))