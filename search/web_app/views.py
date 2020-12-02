"""
Contains Flask view functions associated with certain URLs.
"""


from flask import request, render_template, jsonify, send_from_directory
import json
import copy
import re
import time
import os
import uuid
import xlsxwriter
from . import app, settings, sc, sentView
from .session_management import get_locale, get_session_data, change_display_options, set_session_data
from .auxiliary_functions import jsonp, gzipped, nocache, lang_sorting_key, copy_request_args,\
    distance_constraints_too_complex, remove_sensitive_data
from .search_pipelines import *


@app.route('/search')
def search_page():
    """
    Return HTML of the search page (the main page of the corpus).
    """
    queryString = ''
    if request.query_string is not None:
        queryString = request.query_string.decode('utf-8')

    return render_template('index.html',
                           locale=get_locale(),
                           corpus_name=settings.corpus_name,
                           languages=settings.languages,
                           all_lang_search=settings.all_language_search_enabled,
                           transliterations=settings.transliterations,
                           input_methods=settings.input_methods,
                           media=settings.media,
                           images=settings.images,
                           youtube=settings.media_youtube,
                           gloss_search_enabled=settings.gloss_search_enabled,
                           negative_search_enabled=settings.negative_search_enabled,
                           fulltext_search_enabled=settings.fulltext_search_enabled,
                           debug=settings.debug,
                           subcorpus_selection=settings.search_meta,
                           word_fields_by_tier=json.dumps(settings.word_fields_by_tier,
                                                          ensure_ascii=False, indent=-1),
                           auto_switch_tiers=json.dumps(settings.auto_switch_tiers,
                                                        ensure_ascii=False, indent=-1),
                           generate_dictionary=settings.generate_dictionary,
                           citation=settings.citation,
                           start_page_url=settings.start_page_url,
                           max_request_time=settings.query_timeout + 1,
                           locales=settings.interface_languages,
                           random_seed=get_session_data('seed'),
                           query_string=queryString)


@app.route('/search_sent_query/<int:page>')
@app.route('/search_sent_query')
@jsonp
def search_sent_query(page=0):
    if not settings.debug:
        return jsonify({})
    if request.args and page <= 0:
        query = copy_request_args()
        page = 1
        change_display_options(query)
        set_session_data('last_query', query)
    else:
        query = get_session_data('last_query')
    set_session_data('page', page)
    wordConstraints = sc.qp.wr.get_constraints(query)
    # wordConstraintsPrint = {str(k): v for k, v in wordConstraints.items()}

    if 'para_ids' not in query:
        query, paraIDs = para_ids(query)
        if paraIDs is not None:
            query['para_ids'] = list(paraIDs)

    if (len(wordConstraints) > 0
            and get_session_data('distance_strict')
            and 'sent_ids' not in query
            and distance_constraints_too_complex(wordConstraints)):
        esQuery = sc.qp.html2es(query,
                                searchOutput='sentences',
                                query_size=1,
                                distances=wordConstraints)
        hits = sc.get_sentences(esQuery)
        if ('hits' not in hits
                or 'total' not in hits['hits']
                or hits['hits']['total']['value'] > settings.max_distance_filter):
            esQuery = {}
        else:
            esQuery = sc.qp.html2es(query,
                                    searchOutput='sentences',
                                    distances=wordConstraints)
    else:
        esQuery = sc.qp.html2es(query,
                                searchOutput='sentences',
                                sortOrder=get_session_data('sort'),
                                randomSeed=get_session_data('seed'),
                                query_size=get_session_data('page_size'),
                                page=get_session_data('page'),
                                distances=wordConstraints)
    return jsonify(esQuery)


@app.route('/doc_stats/<metaField>')
def get_doc_stats(metaField):
    """
    Return JSON with basic statistics concerning the distribution
    of corpus documents by values of one metafield. This function
    can be used to visualise (sub)corpus composition.
    """
    if metaField not in settings.search_meta['stat_options']:
        return jsonify({})
    query = copy_request_args()
    change_display_options(query)
    docIDs = subcorpus_ids(query)
    buckets = get_buckets_for_doc_metafield(metaField, langID=-1, docIDs=docIDs)
    return jsonify(buckets)


@app.route('/word_freq_stats/<searchType>')
def get_word_freq_stats(searchType='word'):
    """
    Return JSON with the distribution of a particular kind of words
    or lemmata by frequency rank. This function is used for visualisation.
    Currently, it can only return statistics for a context-insensitive
    query for the whole corpus (the subcorpus constraints are
    discarded from the query). Return a list which contains results
    for each of the query words (the corresponding lines are plotted
    in different colors). Maximum number of simultaneously queried words
    is 10. All words should be in the same language; the language of the
    first word is used.
    """
    htmlQuery = copy_request_args()
    change_display_options(htmlQuery)
    langID = 0
    nWords = 1
    if 'n_words' in htmlQuery and int(htmlQuery['n_words']) > 1:
        nWords = int(htmlQuery['n_words'])
        if nWords > 10:
            nWords = 10
    if searchType not in ('word', 'lemma'):
        searchType = 'word'
    if 'lang1' in htmlQuery and htmlQuery['lang1'] in settings.languages:
        langID = settings.languages.index(htmlQuery['lang1'])
    else:
        return jsonify([])
    results = []
    for iWord in range(1, nWords + 1):
        htmlQuery['lang' + str(iWord)] = htmlQuery['lang1']
        partHtmlQuery = sc.qp.swap_query_words(1, iWord, copy.deepcopy(htmlQuery))
        esQuery = sc.qp.word_freqs_query(partHtmlQuery, searchType=searchType)
        # return jsonify(esQuery)
        if searchType == 'word':
            hits = sc.get_words(esQuery)
        else:
            hits = sc.get_lemmata(esQuery)
        # return jsonify(hits)
        curFreqByRank = sentView.extract_cumulative_freq_by_rank(hits)
        buckets = []
        prevFreq = 0
        if searchType == 'lemma':
            freq_by_rank = settings.lemma_freq_by_rank
        else:
            freq_by_rank = settings.word_freq_by_rank
        for freqRank in sorted(freq_by_rank[langID]):
            bucket = {'name': freqRank, 'n_words': 0}
            if freqRank in curFreqByRank:
                bucket['n_words'] = curFreqByRank[freqRank] / freq_by_rank[langID][freqRank]
                prevFreq = curFreqByRank[freqRank]
            else:
                bucket['n_words'] = prevFreq / freq_by_rank[langID][freqRank]
            buckets.append(bucket)
        results.append(buckets)
    return jsonify(results)


@app.route('/word_stats/<searchType>/<metaField>')
def get_word_stats(searchType, metaField):
    """
    Return JSON with basic statistics concerning the distribution
    of a particular word form by values of one metafield. This function
    can be used to visualise word distributions across genres etc.
    If searchType == 'context', take into account the whole query.
    If searchType == 'compare', treat the query as several sepearate
    one-word queries. If, in this case, the data is to be displayed
    on a bar plot, process only the first word of the query.
    Otherwise, return a list which contains results for each
    of the query words (the corresponding lines are plotted
    in different colors). Maximum number of simultaneously queried words
    is 10. All words should be in the same language; the language of the
    first word is used.
    If the metaField is a document-level field, first split
    the documents into buckets according to its values and then search
    inside each bucket. If it is a sentence-level field, do a single
    search in the sentence index with bucketing.
    """
    if metaField not in settings.search_meta['stat_options']:
        return jsonify([])
    if searchType not in ('compare', 'context'):
        return jsonify([])

    htmlQuery = copy_request_args()
    change_display_options(htmlQuery)
    langID = -1
    if 'lang1' in htmlQuery and htmlQuery['lang1'] in settings.languages:
        langID = settings.languages.index(htmlQuery['lang1'])
    nWords = 1
    if 'n_words' in htmlQuery and int(htmlQuery['n_words']) > 1:
        nWords = int(htmlQuery['n_words'])
        if searchType == 'compare':
            if nWords > 10:
                nWords = 10
            if metaField not in settings.line_plot_meta:
                nWords = 1

    searchIndex = 'words'
    queryWordConstraints = None
    if (searchType == 'context' and nWords > 1) or metaField in settings.sentence_meta:
        searchIndex = 'sentences'
        wordConstraints = sc.qp.wr.get_constraints(htmlQuery)
        set_session_data('word_constraints', wordConstraints)
        if (len(wordConstraints) > 0
                and get_session_data('distance_strict')):
            queryWordConstraints = wordConstraints
    elif searchType == 'context' and 'sentence_index1' in htmlQuery and len(htmlQuery['sentence_index1']) > 0:
        searchIndex = 'sentences'

    results = get_word_buckets(searchType, metaField, nWords, htmlQuery,
                               queryWordConstraints, langID, searchIndex)
    return jsonify(results)


@app.route('/search_sent_json/<int:page>')
@app.route('/search_sent_json')
@jsonp
def search_sent_json(page=-1):
    if page < 0:
        cur_search_context().flush()
        page = 0
    hits = find_sentences_json(page=page)
    remove_sensitive_data(hits)
    return jsonify(hits)


@app.route('/search_sent/<int:page>')
@app.route('/search_sent')
@gzipped
def search_sent(page=-1):
    if page < 0:
        cur_search_context().flush()
        page = 0
    # try:
    hits = find_sentences_json(page=page)
    # except:
    #     return render_template('result_sentences.html', message='Request timeout.')
    cur_search_context().add_sent_to_session(hits)
    hitsProcessed = sentView.process_sent_json(hits,
                                               translit=cur_search_context().translit)
    # hitsProcessed['languages'] = settings.languages
    if len(settings.languages) > 1 and 'hits' in hits and 'hits' in hits['hits']:
        add_parallel(hits['hits']['hits'], hitsProcessed)
    hitsProcessed['languages'].sort(key=lang_sorting_key)
    hitsProcessed['page'] = get_session_data('page')
    hitsProcessed['page_size'] = get_session_data('page_size')
    hitsProcessed['media'] = settings.media
    hitsProcessed['images'] = settings.images
    hitsProcessed['subcorpus_enabled'] = False
    if 'subcorpus_enabled' in hits:
        hitsProcessed['subcorpus_enabled'] = True
    cur_search_context().sync_page_data(hitsProcessed['page'], hitsProcessed)

    return render_template('result_sentences.html', data=hitsProcessed)


@app.route('/get_sent_context/<int:n>')
@jsonp
def get_sent_context(n):
    """
    Retrieve the neighboring sentences for the currently
    viewed sentence number n. Take into account how many
    times this particular context has been expanded and
    whether expanding it further is allowed.
    """
    if n < 0:
        return jsonify({})
    sentData = cur_search_context().sentence_data
    # return jsonify({"l": len(sentData), "i": sentData[n]})
    if sentData is None or n >= len(sentData) or 'languages' not in sentData[n]:
        return jsonify({})
    curSentData = sentData[n]
    if curSentData['times_expanded'] >= settings.max_context_expand >= 0:
        return jsonify({})
    context = {'n': n, 'languages': {lang: {} for lang in curSentData['languages']},
               'src_alignment': {}}
    neighboringIDs = {lang: {'next': -1, 'prev': -1} for lang in curSentData['languages']}
    for lang in curSentData['languages']:
        try:
            langID = settings.languages.index(lang)
        except:
            # Language + number of the translation version: chop off the number
            langID = settings.languages.index(re.sub('_[0-9]+$', '', lang))
        for side in ['next', 'prev']:
            curCxLang = context['languages'][lang]
            if side + '_id' in curSentData['languages'][lang]:
                curCxLang[side] = sc.get_sentence_by_id(curSentData['languages'][lang][side + '_id'])
            if (side in curCxLang
                    and len(curCxLang[side]) > 0
                    and 'hits' in curCxLang[side]
                    and 'hits' in curCxLang[side]['hits']
                    and len(curCxLang[side]['hits']['hits']) > 0):
                lastSentNum = cur_search_context().last_sent_num + 1
                curSent = curCxLang[side]['hits']['hits'][0]
                if '_source' in curSent and 'lang' not in curSent['_source']:
                    curCxLang[side] = ''
                    continue
                langReal = lang
                # lang is an identifier of the tier for parallel corpora, i.e.
                # the language of the original unexpanded sentence.
                # langReal is the real language of the expanded context.
                if '_source' in curSent and curSent['_source']['lang'] != langID:
                    langReal = settings.languages[curSent['_source']['lang']]
                if '_source' in curSent and side + '_id' in curSent['_source']:
                    neighboringIDs[lang][side] = curSent['_source'][side + '_id']
                expandedContext = sentView.process_sentence(curSent,
                                                            numSent=lastSentNum,
                                                            getHeader=False,
                                                            lang=langReal,
                                                            translit=cur_search_context().translit)
                curCxLang[side] = expandedContext['languages'][langReal]['text']
                if settings.media:
                    sentView.relativize_src_alignment(expandedContext, curSentData['src_alignment_files'])
                    context['src_alignment'].update(expandedContext['src_alignment'])
                cur_search_context().last_sent_num = lastSentNum
            else:
                curCxLang[side] = ''
    cur_search_context().update_expanded_contexts(context, neighboringIDs)
    return jsonify(context)


@app.route('/search_lemma_query')
@jsonp
def search_lemma_query():
    return search_word_query(searchType='lemma')


@app.route('/search_word_query')
@jsonp
def search_word_query(searchType='word'):
    if not settings.debug:
        return jsonify({})
    query = copy_request_args()
    change_display_options(query)
    if 'doc_ids' not in query:
        docIDs = subcorpus_ids(query)
        if docIDs is not None:
            query['doc_ids'] = docIDs
    else:
        docIDs = query['doc_ids']

    searchIndex = 'words'
    sortOrder = get_session_data('sort')
    queryWordConstraints = None
    nWords = 1
    if 'n_words' in query and int(query['n_words']) > 1:
        nWords = int(query['n_words'])
        searchIndex = 'sentences'
        sortOrder = 'random'  # in this case, the words are sorted after the search
        wordConstraints = sc.qp.wr.get_constraints(query)
        set_session_data('word_constraints', wordConstraints)
        if (len(wordConstraints) > 0
            and get_session_data('distance_strict')):
            queryWordConstraints = wordConstraints

    query = sc.qp.html2es(query,
                          searchOutput='words',
                          sortOrder=sortOrder,
                          randomSeed=get_session_data('seed'),
                          query_size=get_session_data('page_size'),
                          distances=queryWordConstraints)
    if searchType == 'lemma':
        sc.qp.lemmatize_word_query(query)
    return jsonify(query)


@app.route('/search_lemma_json')
@jsonp
def search_lemma_json():
    return search_word_json(searchType='lemma')


@app.route('/search_word_json/<int:page>')
@app.route('/search_word_json')
@jsonp
def search_word_json(searchType='word', page=0):
    query = copy_request_args()
    change_display_options(query)
    if page <= 0:
        page = 1
        set_session_data('page', page)
    if 'doc_ids' not in query:
        docIDs = subcorpus_ids(query)
        if docIDs is not None:
            query['doc_ids'] = docIDs
    else:
        docIDs = query['doc_ids']

    searchIndex = 'words'
    sortOrder = get_session_data('sort')
    queryWordConstraints = None
    nWords = 1
    if 'n_words' in query and int(query['n_words']) > 1:
        nWords = int(query['n_words'])
        searchIndex = 'sentences'
        sortOrder = 'random'  # in this case, the words are sorted after the search
        wordConstraints = sc.qp.wr.get_constraints(query)
        set_session_data('word_constraints', wordConstraints)
        if (len(wordConstraints) > 0
                and get_session_data('distance_strict')):
            queryWordConstraints = wordConstraints
    elif 'sentence_index1' in query and len(query['sentence_index1']) > 0:
        searchIndex = 'sentences'
        sortOrder = 'random'

    query = sc.qp.html2es(query,
                          searchOutput='words',
                          sortOrder=sortOrder,
                          randomSeed=get_session_data('seed'),
                          query_size=get_session_data('page_size'),
                          page=get_session_data('page'),
                          distances=queryWordConstraints)

    hits = []
    if searchIndex == 'words':
        if docIDs is None:
            if searchType == 'lemma':
                sc.qp.lemmatize_word_query(query)
                hits = sc.get_lemmata(query)
            else:
                hits = sc.get_words(query)
        else:
            hits = sc.get_word_freqs(query)
    elif searchIndex == 'sentences':
        iSent = 0
        for hit in sc.get_all_sentences(query):
            if iSent >= 5:
                break
            iSent += 1
            hits.append(hit)

    return jsonify(hits)


@app.route('/search_lemma/<int:page>')
@app.route('/search_lemma')
def search_lemma(page=0):
    return search_word(searchType='lemma', page=page)


@app.route('/search_word/<int:page>')
@app.route('/search_word')
def search_word(searchType='word', page=0):
    set_session_data('progress', 0)
    if request.args and page <= 0:
        query = copy_request_args()
        page = 1
        change_display_options(query)
        if get_session_data('sort') not in ('random', 'freq', 'wf', 'lemma'):
            set_session_data('sort', 'random')
        set_session_data('last_query', query)
    else:
        query = get_session_data('last_query')
    set_session_data('page', page)
    if 'doc_ids' not in query:
        docIDs = subcorpus_ids(query)
        if docIDs is not None:
            query['doc_ids'] = docIDs
    else:
        docIDs = query['doc_ids']

    searchIndex = 'words'
    sortOrder = get_session_data('sort')
    wordConstraints = None
    queryWordConstraints = None
    constraintsTooComplex = False
    nWords = 1
    if 'n_words' in query and int(query['n_words']) > 1:
        nWords = int(query['n_words'])
        searchIndex = 'sentences'
        sortOrder = 'random'    # in this case, the words are sorted after the search
        wordConstraints = sc.qp.wr.get_constraints(query)
        set_session_data('word_constraints', wordConstraints)
        if (len(wordConstraints) > 0
                and get_session_data('distance_strict')):
            queryWordConstraints = wordConstraints
            if distance_constraints_too_complex(wordConstraints):
                constraintsTooComplex = True
    elif 'sentence_index1' in query and len(query['sentence_index1']) > 0:
        searchIndex = 'sentences'
        sortOrder = 'random'

    query = sc.qp.html2es(query,
                          searchOutput='words',
                          sortOrder=sortOrder,
                          randomSeed=get_session_data('seed'),
                          query_size=get_session_data('page_size'),
                          page=get_session_data('page'),
                          distances=queryWordConstraints,
                          includeNextWordField=constraintsTooComplex)

    maxRunTime = time.time() + settings.query_timeout
    hitsProcessed = {}
    if searchIndex == 'words':
        if docIDs is None:
            if searchType == 'lemma':
                sc.qp.lemmatize_word_query(query)
                hits = sc.get_lemmata(query)
            else:
                hits = sc.get_words(query)
            hitsProcessed = sentView.process_word_json(hits, docIDs,
                                                       searchType=searchType,
                                                       translit=cur_search_context().translit)
        else:
            hits = sc.get_word_freqs(query)
            hitsProcessed = sentView.process_word_subcorpus_json(hits, docIDs,
                                                                 translit=cur_search_context().translit)

    elif searchIndex == 'sentences':
        hitsProcessed = {'n_occurrences': 0, 'n_sentences': 0, 'n_docs': 0,
                         'total_freq': 0,
                         'words': [], 'doc_ids': set(), 'word_ids': {}}
        for hit in sc.get_all_sentences(query):
            if constraintsTooComplex:
                if not sc.qp.wr.check_sentence(hit, wordConstraints, nWords=nWords):
                    continue
            sentView.add_word_from_sentence(hitsProcessed, hit, nWords=nWords)
            if hitsProcessed['total_freq'] >= 2000 and time.time() > maxRunTime:
                hitsProcessed['timeout'] = True
                break
        hitsProcessed['n_docs'] = len(hitsProcessed['doc_ids'])
        if hitsProcessed['n_docs'] > 0:
            sentView.process_words_collected_from_sentences(hitsProcessed,
                                                            sortOrder=get_session_data('sort'),
                                                            pageSize=get_session_data('page_size'))

    hitsProcessed['media'] = settings.media
    hitsProcessed['images'] = settings.images
    set_session_data('progress', 100)
    bShowNextButton = True
    if 'words' not in hitsProcessed or len(hitsProcessed['words']) != get_session_data('page_size'):
        bShowNextButton = False
    return render_template('result_words.html',
                           data=hitsProcessed,
                           word_table_fields=settings.word_table_fields,
                           word_search_display_gr=settings.word_search_display_gr,
                           display_freq_rank=settings.display_freq_rank,
                           search_type=searchType,
                           page=page,
                           show_next=bShowNextButton)


@app.route('/search_doc_query')
@jsonp
def search_doc_query():
    if not settings.debug:
        return jsonify({})
    query = copy_request_args()
    change_display_options(query)
    query = sc.qp.subcorpus_query(query,
                                  sortOrder=get_session_data('sort'),
                                  query_size=settings.max_docs_retrieve)
    return jsonify(query)


@app.route('/search_doc_json')
@jsonp
def search_doc_json():
    query = copy_request_args()
    change_display_options(query)
    query = sc.qp.subcorpus_query(query,
                                  sortOrder=get_session_data('sort'),
                                  query_size=settings.max_docs_retrieve)
    hits = sc.get_docs(query)
    return jsonify(hits)


@app.route('/search_doc')
@jsonp
def search_doc():
    query = copy_request_args()
    change_display_options(query)
    query = sc.qp.subcorpus_query(query,
                                  sortOrder=get_session_data('sort'),
                                  query_size=settings.max_docs_retrieve)
    hits = sc.get_docs(query)
    hitsProcessed = sentView.process_docs_json(hits,
                                               exclude=get_session_data('excluded_doc_ids'),
                                               corpusSize=settings.corpus_size)
    hitsProcessed['media'] = settings.media
    hitsProcessed['images'] = settings.images
    return render_template('result_docs.html', data=hitsProcessed)


@app.route('/get_word_fields')
def get_word_fields():
    """
    Return HTML with form inputs representing all additional
    word-level annotation fields.
    """
    return render_template('common_additional_search_fields.html',
                           word_fields=settings.word_fields,
                           sentence_meta=settings.sentence_meta,
                           multiple_choice_fields=settings.multiple_choice_fields,
                           int_meta_fields=settings.integer_meta_fields,
                           sentence_meta_values=settings.sentence_meta_values,
                           default_values=settings.default_values,
                           ambiguous_analyses=settings.ambiguous_analyses)


@app.route('/media/<path:path>')
def send_media(path):
    """
    Return the requested media file.
    """
    return send_from_directory(os.path.join('../media', settings.corpus_name), path)

@app.route('/img/<path:path>')
def send_image(path):
    """
    Return the requested image file.
    """
    return send_from_directory(os.path.join('../img', settings.corpus_name), path)


@app.route('/download_cur_results_csv')
@nocache
def download_cur_results_csv():
    """
    Write all sentences the user has already seen, except the
    toggled off ones, to a CSV file. Return the contents of the file.
    """
    pageData = cur_search_context().page_data
    if pageData is None or len(pageData) <= 0:
        return ''
    result = cur_search_context().prepare_results_for_download
    return '\n'.join(['\t'.join(s) for s in result if len(s) > 0])


@app.route('/download_cur_results_xlsx')
@nocache
def download_cur_results_xlsx():
    """
    Write all sentences the user has already seen, except the
    toggled off ones, to an XSLX file. Return the file.
    """
    pageData = cur_search_context().page_data
    if pageData is None or len(pageData) <= 0:
        return ''
    results = cur_search_context().prepare_results_for_download
    XLSXFilename = 'results-' + str(uuid.uuid4()) + '.xlsx'
    if not os.path.exists('tmp'):
        os.makedirs('tmp')
    workbook = xlsxwriter.Workbook('tmp/' + XLSXFilename)
    worksheet = workbook.add_worksheet('Search results')
    for i in range(len(results)):
        for j in range(len(results[i])):
            worksheet.write(i, j, results[i][j])
    workbook.close()
    return send_from_directory('../tmp', XLSXFilename)


@app.route('/toggle_sentence/<int:sentNum>')
def toggle_sentence(sentNum):
    """
    Togle currently viewed sentence with the given number on or off.
    The sentences that have been switched off are not written to the
    CSV/XLSX when the user wants to download the search results.
    """
    pageData = cur_search_context().page_data
    page = get_session_data('page')
    if page is None or page == '':
        page = 0
    if pageData is None or page is None or page not in pageData:
        return json.dumps(pageData)
    if sentNum < 0 or sentNum >= len(pageData[page]):
        return ''
    pageData[page][sentNum]['toggled_off'] = not pageData[page][sentNum]['toggled_off']
    return ''


@app.route('/toggle_doc/<int:docID>')
def toggle_document(docID):
    """
    Togle given docID on or off. The documents that have been switched off
    are not included in the search.
    """
    excludedDocIDs = get_session_data('excluded_doc_ids')
    nWords = sc.get_n_words_in_document(docId=docID)
    sizePercent = round(nWords * 100 / settings.corpus_size, 3)
    if docID in excludedDocIDs:
        excludedDocIDs.remove(docID)
        nDocs = 1
    else:
        excludedDocIDs.add(docID)
        nWords = -1 * nWords
        sizePercent = -1 * sizePercent
        nDocs = -1
    return jsonify({'n_words': nWords, 'n_docs': nDocs, 'size_percent': sizePercent})


@app.route('/clear_subcorpus')
def clear_subcorpus():
    """
    Flush the list of excluded document IDs.
    """
    set_session_data('excluded_doc_ids', set())
    return ''


@app.route('/get_gramm_selector/<lang>')
def get_gramm_selector(lang=''):
    """
    Return HTML of the grammatical tags selection dialogue for the given language.
    """
    if lang not in settings.lang_props or 'gramm_selection' not in settings.lang_props[lang]:
        return ''
    grammSelection = settings.lang_props[lang]['gramm_selection']
    return render_template('select_gramm.html', tag_table=grammSelection)


@app.route('/get_add_field_selector/<field>')
def get_add_field_selector(field=''):
    """
    Return HTML of the tags selection dialogue for an additional word-level field.
    """
    if field not in settings.multiple_choice_fields:
        return ''
    tagSelection = settings.multiple_choice_fields[field]
    return render_template('select_gramm.html', tag_table=tagSelection)


@app.route('/get_gloss_selector/<lang>')
def get_gloss_selector(lang=''):
    """
    Return HTML of the gloss selection dialogue for the given language.
    """
    if lang not in settings.lang_props or 'gloss_selection' not in settings.lang_props[lang]:
        return ''
    glossSelection = settings.lang_props[lang]['gloss_selection']
    return render_template('select_gloss.html', glosses=glossSelection)


@app.route('/get_glossed_sentence/<int:n>')
def get_glossed_sentence(n):
    """
    Return a tab-delimited glossed sentence ready for insertion into
    a linguistic paper.
    """
    if n < 0:
        return ''
    sentData = cur_search_context().sentence_data
    if sentData is None or n >= len(sentData) or 'languages' not in sentData[n]:
        return ''
    curSentData = sentData[n]
    for langView in curSentData['languages']:
        lang = langView
        try:
            langID = settings.languages.index(langView)
        except:
            # Language + number of the translation version: chop off the number
            langID = settings.languages.index(re.sub('_[0-9]+$', '', langView))
            lang = settings.languages[langID]
        if langID != 0:
            continue  # for now
        result = sentView.get_glossed_sentence(curSentData['languages'][langView]['source'], lang=lang)
        if type(result) == str:
            return result
        return ''
    return ''


@app.route('/set_locale/<lang>')
def set_locale(lang=''):
    if lang not in settings.interface_languages:
        return
    set_session_data('locale', lang)
    return ''


@app.route('/help_dialogue')
def help_dialogue():
    l = get_locale()
    return render_template('help_dialogue_' + l + '.html',
                           media=settings.media,
                           gloss_search_enabled=settings.gloss_search_enabled)


@app.route('/dictionary/<lang>')
def get_dictionary(lang):
    if not settings.generate_dictionary:
        return 'No dictionary available for this language.'
    dictFilename = 'dictionary_' + settings.corpus_name + '_' + lang + '.html'
    try:
        return render_template(dictFilename)
    except:
        return ''