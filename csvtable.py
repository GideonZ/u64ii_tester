import csv
import unicodedata
import io
    
def normalize_caseless(text):
    return unicodedata.normalize("NFKD", text.upper().lower()) #-- .decode('unicode-escape')

def caseless_equal(left, right):
    if len(left) == 0:
        return False
    if len(right) == 0:
        return False
    return normalize_caseless(left) == normalize_caseless(right)

def caseless_in(left, right):
    if len(left) == 0:
        return False
    if len(right) == 0:
        return False
    a = normalize_caseless(left)
    b = normalize_caseless(right)
    if (a in b):
        return True
    return b in a

class CsvTable(object):
    def __init__(self, filename, delimiter = ',', skip_first = False, encoding = 'utf-8', skip_bom = False):
        import io
        with io.open(filename, 'r', encoding = encoding) as csvfile:
            if skip_bom:
                csvfile.read(1)
            if skip_first:
                csvfile.next()
                
            Reader = csv.DictReader(csvfile, dialect='excel', delimiter=delimiter)
            self.columns = Reader.fieldnames
            self.rows = []
            for row in Reader:
                self.rows.append(row)

    @staticmethod
    def create(filename, fields, rows, delimiter = ',', encoding = 'utf-8'):
        with io.open(filename, "wb") as outfile:
            header = delimiter.join(fields) + "\n"
            outfile.write(header.encode(encoding, errors = 'ignore'))
            for row in rows:
                elements = [ ]
                for f in fields:
                    if f in row:
                        st = str(row[f])
                        if len(st) > 0:
                            elements.append('"' + str(row[f]) + '"')
                        else:
                            elements.append('')
                    else:
                        elements.append('')
                line = delimiter.join(elements) + "\n"
                outfile.write(line.encode(encoding, errors = 'ignore'))
        
    def sort(self, Key):
        self.rows = sorted(self.rows, key = lambda k: k[Key])
        
    def find_first(self, key, value):
        for i in self.rows:
            if i[key] == value:
                return i
                
    def find_entries(self, key, value):
        ret = []
        for i in self.rows:
            if i[key] == value:
                ret.append(i)
        return ret
    
    def find_range(self, key, _from, _to):
        ret = []
        for i in self.rows:
            if (i[key] >= _from) and (i[key] < _to):
                ret.append(i)
        return ret

    def find_last(self, match):
        for i in reversed(self.rows):
            found = True
            for k in match.keys():
                if not caseless_equal(i[k], match[k]):
                    found = False
                    break
            if found:
                return i

    def find_substring(self, match):
        for i in reversed(self.rows):
            found = True
            for k in match.keys():
                if len(i[k]) < 6 or len(match[k]) < 6 or not caseless_in(i[k], match[k]):
                    found = False
                    break
            if found:
                return i

    def filter_remove(self, match):
        n = []
        for i in self.rows:
            match = True
            for k in match.keys():
                if not caseless_equal(i[k], match[k]):
                    match = False
                    break
            if not match:
                n.append(i)
        
        self.rows = n
            
    def filter_keep(self, match):
        n = []
        for i in self.rows:
            match = True
            for k in match.keys():
                if not caseless_equal(i[k], match[k]):
                    match = False
                    break
            if match:
                n.append(i)
        
        self.rows = n

    def write_back(self, filename, rows=None):
        if rows == None:
            rows = self.rows
        writer = csv.DictWriter(open(filename, 'w'), fieldnames = self.columns) #, dialect='excel')
        writer.writerow(dict((fn,fn) for fn in self.columns))
        for row in rows:
            writer.writerow(row)
    