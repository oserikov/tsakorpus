import re
import copy
import html


class TextCleaner:
    """
    Contains methods for cleaning a string from things like
    HTML entities etc.
    It is assumed tha the cleaner can be language-dependent.
    """
    rxTags = re.compile('</?(?:a|img|span|div|p|body|html|head)(?: [^<>]+)?>|[\0⌐-♯]+',
                        flags=re.DOTALL)
    rxSpaces1 = re.compile(' {2,}| +|\t+|&nbsp;| ', flags=re.DOTALL)
    rxSpaces2 = re.compile('(?: *\n)+ *', flags=re.DOTALL)
    rxPuncWords = re.compile('([,!?:;·;·)\\]>])([\\w(\\[<])')
    rxQuotesL = re.compile('([\\s(\\[{<\\-])"([\\w\\-\'`´‘’‛@.,-‒–—―•])',
                           flags=re.DOTALL)
    rxQuotesR = re.compile('([\\w\\-\'`´‘’‛/@.,-‒–—―•,!?:;·;·])"([\\s)\\]}>\\-.,!])',
                           flags=re.DOTALL)
    rxNonstandardQuotesL = re.compile('[“]', flags=re.DOTALL)
    rxNonstandardQuotesR = re.compile('[”]', flags=re.DOTALL)

    rxCyrISmall = re.compile('(?<=[Ѐ-ԧ])i|i(?=[Ѐ-ԧ])')
    rxCyrIBig = re.compile('(?<=[Ѐ-ԧ])I|I(?=[Ѐ-ԧ])')
    rxCyrAeSmall = re.compile('(?<=[Ѐ-ԧ])æ|æ(?=[Ѐ-ԧ])')
    rxCyrAeBig = re.compile('(?<=[Ѐ-ԧ])Æ|Æ(?=[Ѐ-ԧ])')
    rxCyrSchwaSmall = re.compile('(?<=[Ѐ-ԧ])[ǝə]|[ǝə](?=[Ѐ-ԧ])')
    rxCyrSchwaBig = re.compile('(?<=[Ѐ-ԧ])Ə|Ə(?=[Ѐ-ԧ])')
    rxCyrHSmall = re.compile('(?<=[Ѐ-ԧ])h|h(?=[Ѐ-ԧ])')
    rxCyrHBig = re.compile('(?<=[Ѐ-ԧ])H|H(?=[Ѐ-ԧ])')

    def __init__(self, settings):
        self.settings = copy.deepcopy(settings)

    def clean_text(self, text):
        """
        Main method that calls separate step-by-step procedures.
        :param text: 
        :return: 
        """
        text = self.convert_html(text)
        text = self.clean_spaces(text)
        text = self.separate_words(text)
        if self.settings['convert_quotes']:
            text = self.convert_quotes(text)
        text = self.clean_other(text)
        return text

    def convert_html(self, text):
        text = self.rxTags.sub('', text)  # deletes all tags in angle brackets
        text = html.unescape(text)
        return text

    def clean_spaces(self, text):
        text = self.rxSpaces1.sub(' ', text.strip())  # unify all spaces
        text = self.rxSpaces2.sub('\n ', text)  # normalize new lines
        return text

    def separate_words(self, text):
        # punctuation inside a word
        text = self.rxPuncWords.sub(u'\\1 \\2', text)  # adds a space between punctuation and next letter
        return text

    def convert_quotes(self, text):
        text = self.rxQuotesL.sub('\\1«\\2', text)
        text = self.rxQuotesR.sub('\\1»\\2', text)
        text = self.rxNonstandardQuotesL.sub(self.settings['left_quot_mark'], text)
        text = self.rxNonstandardQuotesR.sub(self.settings['right_quot_mark'], text)
        return text

    def clean_other(self, text):
        if self.settings['languages'][0] == 'udmurt':
            text = text.replace('ü', 'ӥ')
        if self.settings['languages'][0] in ['ukrainian', 'kazakh', 'komi']:
            text = self.rxCyrISmall.sub('і', text)
            text = self.rxCyrIBig.sub('І', text)
        if self.settings['languages'][0] in ['kazakh', 'tatar', 'bashkir', 'kalmyk']:
            text = self.rxCyrHSmall.sub('һ', text)
            text = self.rxCyrHBig.sub('Һ', text)
        if self.settings['languages'][0] in ['kazakh', 'tatar', 'bashkir']:
            text = self.rxCyrSchwaSmall.sub('ә', text)
            text = self.rxCyrSchwaBig.sub('Ә', text)
        if self.settings['languages'][0] in ['ossetic', 'iron', 'digor']:
            text = self.rxCyrAeSmall.sub('ӕ', text)
            text = self.rxCyrAeBig.sub('Ӕ', text)
        text = text.replace(u'…', u'...')
        text = text.replace(u'\\', u'/')
        return text
